"""PCM output DAC clock is the master; MIDI follows its monotonic projection."""
import bisect
import queue
import threading
import time
from dataclasses import dataclass, field
import bootstrap
import numpy as np
import sounddevice as sd
from midi_out import MidiOutput
from song import RATE

@dataclass
class Settings:
    mode: str = 'auto'
    audio_device: int | None = None
    midi_devices: tuple = (None, None, None, None)
    midi_sources: tuple = (0, 1, 0, 1)
    track_routes: dict | None = None
    audio_offset: float = 0.0
    midi_offset: float = 0.0
    master: float = 0.75
    gains: list = field(default_factory=list)

def selected_tracks(song, variant, mode):
    if mode == 'midi':
        return []
    if mode in ('mix', 'audio'):
        return list(range(len(song.pcm)))
    if variant.segmented:
        raise ValueError('This MDT uses type-14 segmented audio events. Automatic scheduling is not implemented; use MIDI only or manual mixing.')
    return list(dict.fromkeys(variant.selected))

def mix_block(song, variant, tracks, frame, count, settings):
    """Pure deterministic PCM rendering, also used by offline synchronization tests."""
    result = np.zeros((count, 2), dtype=np.float32)
    for track in tracks:
        if track >= len(song.pcm):
            continue
        audio = song.pcm[track]
        gate = variant.starts.get(track, 0.0) if settings.mode == 'auto' else 0.0
        source_start = frame - round(settings.audio_offset * RATE)
        left = max(0, -source_start, round((gate + settings.audio_offset) * RATE) - frame)
        right = min(count, len(audio) - source_start)
        if right > left:
            gain = settings.gains[track] if track < len(settings.gains) else 1.0
            result[left:right] += audio[source_start + left:source_start + right] * gain
    result *= settings.master
    np.clip(result, -1, 1, out=result)
    return result

class PlayerEngine:

    def __init__(self, stream_factory=None, midi_factory=None, clock=time.perf_counter):
        self.stream_factory = stream_factory or sd.OutputStream
        self.midi_factory = midi_factory or MidiOutput
        self.clock = clock
        self.commands = queue.Queue()
        self.messages = queue.Queue()
        self.lock = threading.RLock()
        self.song = None
        self.variant = None
        self.settings = Settings()
        self.tracks = []
        self.duration = 0.0
        self.frame = 0
        self.anchor = None
        self.playing = False
        self.stream = None
        self.outputs = {}
        self.cursor = 0
        self.times = []
        self.closed = False
        self.worker = threading.Thread(target=self._run, name='Playback', daemon=True)
        self.worker.start()

    def command(self, name, *args):
        self.commands.put((name, args))

    def configure(self, song, index, settings):
        self.command('configure', song, index, settings)

    def position(self):
        with self.lock:
            if self.playing and self.anchor is not None:
                return min(self.duration, max(0.0, self.clock() - self.anchor))
            return min(self.duration, max(0.0, self.frame / RATE))

    def snapshot(self):
        with self.lock:
            return (self.position(), self.duration, self.playing)

    def _panic(self):
        for output in self.outputs.values():
            output.panic()

    def _halt(self, capture=True):
        with self.lock:
            if capture:
                self.frame = round(self.position() * RATE)
            self.playing = False
            self.anchor = None
        if self.stream is not None:
            self.stream.abort()
        self._panic()

    def _dispose(self):
        self._halt()
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        for output in set(self.outputs.values()):
            output.close()
        self.outputs.clear()

    def _configure(self, song, index, settings):
        self._dispose()
        if not 1 <= len(settings.midi_devices) <= 4:
            raise ValueError('Select 1 to 4 MIDI output ports')
        enabled = [d for d in settings.midi_devices if d is not None]
        if len(enabled) != len(set(enabled)):
            raise ValueError('Use different devices for MIDI A/B/C/D. Enable only one output for a single synthesizer.')
        if len(settings.midi_sources) < len(settings.midi_devices) or any((s not in (0, 1) for s in settings.midi_sources)):
            raise ValueError('Each MIDI output must select logical source A or B')
        variant = song.variants[index]
        if settings.track_routes is not None:
            known = {part.id for part in variant.parts}
            if any((track not in known for track in settings.track_routes)):
                raise ValueError('The routing table references a missing MIDI track')
            if any((not isinstance(port, int) or not 0 <= port < len(settings.midi_devices) for ports in settings.track_routes.values() for port in ports)):
                raise ValueError('Track outputs must be MIDI ports A/B/C/D')
            settings.track_routes = {track: tuple(sorted(set(ports))) for track, ports in settings.track_routes.items()}
        tracks = selected_tracks(song, variant, settings.mode)
        missing = [t for t in tracks if t >= len(song.pcm)]
        if missing:
            raise ValueError(f'Missing SD3 audio resource {missing}; select the matching SD3 or use MIDI only')
        if settings.mode != 'midi' and (not song.pcm) and (settings.mode in ('audio', 'mix')):
            raise ValueError('No SD3 loaded')
        with self.lock:
            self.song, self.variant, self.settings, self.tracks = (song, variant, settings, tracks)
            self.frame = 0
            self.duration = max([variant.duration + max(0, settings.midi_offset)] + [len(song.pcm[t]) / RATE + max(0, settings.audio_offset) for t in tracks])
            self.times = [e.time + settings.midi_offset for e in variant.events]
            self.cursor = 0
        try:
            if settings.mode != 'audio':
                for port, device in enumerate(settings.midi_devices):
                    if device is not None:
                        self.outputs[port] = self.midi_factory(device)
            self.stream = self.stream_factory(samplerate=RATE, channels=2, dtype='float32', blocksize=512, latency='low', device=settings.audio_device, callback=self._callback)
        except Exception:
            for output in set(self.outputs.values()):
                output.close()
            self.outputs.clear()
            self.song = None
            raise
        self.messages.put(('ready', f"{getattr(variant, 'label', 'MDT')} {index} ready; audio {tracks}；{self.duration:.2f} s"))
        if settings.mode != 'audio' and (not self.outputs):
            self.messages.put(('warning', 'No MIDI output selected; events are tracked without sound'))

    def _callback(self, outdata, frames, info, status):
        outdata.fill(0)
        try:
            with self.lock:
                if not self.playing:
                    return
                frame = self.frame
                if frame < round(self.duration * RATE):
                    self.anchor = self.clock() + float(info.outputBufferDacTime - info.currentTime) - frame / RATE
                if frame < round(self.duration * RATE):
                    outdata[:] = mix_block(self.song, self.variant, self.tracks, frame, frames, self.settings)
                    self.frame += frames
            if status:
                self.messages.put(('warning', str(status)))
        except Exception as ex:
            self.messages.put(('error', f'Audio callback failed: {ex}'))
            self.commands.put(('pause', ()))

    def _destinations(self, event):
        routes = self.settings.track_routes
        if routes is not None:
            if event.shared and event.port != 0:
                return ()
            return tuple((p for p in routes.get(event.track, ()) if p in self.outputs))
        return tuple((p for p in self.outputs if self.settings.midi_sources[p] == event.port))

    def _send(self, event):
        for port in self._destinations(event):
            self.outputs[port].send(event.data)

    def _chase(self, position):
        """Replay ordered controller/NRPN setup and restore sustained notes after seeking."""
        self._panic()
        self.cursor = bisect.bisect_left(self.times, position)
        active = {}
        sustain = {}
        for event in self.variant.events[:self.cursor]:
            msg = event.data
            kind, channel = (msg[0] >> 4, msg[0] & 15)
            for port in self._destinations(event):
                key = (port, channel, msg[1] if len(msg) > 1 else 0)
                if kind == 9 and msg[2]:
                    active[key] = (event, False)
                elif kind == 8 or (kind == 9 and (not msg[2])):
                    if sustain.get(key[:2], False) and key in active:
                        active[key] = (active[key][0], True)
                    else:
                        active.pop(key, None)
                else:
                    self.outputs[port].send(msg)
                    if kind == 11 and msg[1] == 64:
                        sustain[key[:2]] = msg[2] >= 64
                        if msg[2] < 64:
                            active = {k: v for k, v in active.items() if not (k[:2] == key[:2] and v[1])}
                    elif kind == 11 and msg[1] in (120, 123):
                        active = {k: v for k, v in active.items() if k[:2] != key[:2]}
        for (port, channel, note), (event, released) in active.items():
            self.outputs[port].send(event.data)
            if released:
                self.outputs[port].send(bytes([128 | channel, note, 0]))

    def _play(self):
        if self.song is None or self.stream is None:
            raise ValueError('Load a song and apply playback settings first')
        if self.playing:
            return
        if self.frame / RATE >= self.duration:
            self.frame = 0
        self._chase(self.frame / RATE)
        with self.lock:
            self.anchor = None
            self.playing = True
        self.stream.start()

    def _run(self):
        while not self.closed:
            try:
                try:
                    name, args = self.commands.get(timeout=0.002)
                    if name == 'configure':
                        self._configure(*args)
                    elif name == 'play':
                        self._play()
                    elif name == 'pause':
                        self._halt()
                    elif name == 'stop':
                        self._halt(False)
                        self.frame = 0
                    elif name == 'seek':
                        was_playing = self.playing
                        self._halt(False)
                        self.frame = round(max(0, min(self.duration, args[0])) * RATE)
                        if was_playing:
                            self._play()
                    elif name == 'mix':
                        with self.lock:
                            self.settings.master, self.settings.gains = args
                    elif name == 'close':
                        self._dispose()
                        self.closed = True
                except queue.Empty:
                    pass
                if self.playing and self.anchor is not None and (self.clock() >= self.anchor):
                    position = self.position()
                    while self.cursor < len(self.times) and self.times[self.cursor] <= position:
                        self._send(self.variant.events[self.cursor])
                        self.cursor += 1
                    if position >= self.duration:
                        self.frame = round(self.duration * RATE)
                        self._halt(False)
                        self.messages.put(('ended', 'Playback finished'))
                for output in set(self.outputs.values()):
                    output.collect()
            except Exception as ex:
                try:
                    self._halt()
                except Exception:
                    self.playing = False
                self.messages.put(('error', str(ex)))

    def close(self):
        self.command('close')
        self.worker.join(timeout=5)
