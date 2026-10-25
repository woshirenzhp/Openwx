"""Decode a song into PCM tracks and a tempo-aware MIDI event timeline."""
import bisect
import io
import struct
from dataclasses import dataclass, field
from pathlib import Path
import bootstrap
import av
import numpy as np
from formats import decompress, parse_streams
RATE = 44100

def resources(data):
    if len(data) < 8:
        raise ValueError('Resource header is shorter than 8 bytes')
    n = struct.unpack_from('<I', data, 4)[0]
    if n > 4096 or 8 + n * 8 > len(data):
        raise ValueError('Invalid resource count')
    result = []
    for i in range(n):
        off, size = struct.unpack_from('<II', data, 8 + i * 8)
        if off < 8 + n * 8 or off + size > len(data):
            raise ValueError('Resource extends beyond the file')
        result.append((off, size))
    ordered = sorted(result)
    if any((a + n > b for (a, n), (b, _) in zip(ordered, ordered[1:]))):
        raise ValueError('Resource regions overlap')
    return [data[o:o + n] for o, n in result]

def read_mi3(path):
    data = Path(path).read_bytes()
    if data[:4] != b'MIDI' or len(data) < 48 or struct.unpack_from('<I', data, 4)[0] != 3:
        raise ValueError('A supported MI3 version 3 container is required')
    mids = []
    spans = []
    for i in range(5):
        off, size = struct.unpack_from('<II', data, 8 + i * 8)
        if off < 48 or size < 4 or off + size > len(data):
            raise ValueError('Invalid MI3 block boundaries')
        spans.append((off, size))
        if data[off:off + 4] == b'MID\x03':
            for raw in resources(data[off:off + size]):
                if len(raw) < 8:
                    raise ValueError('Incomplete MID compression header')
                method, length = struct.unpack_from('<II', raw)
                if method != 1 or length > 64 * 1024 * 1024:
                    raise ValueError('Unsupported music compression method or length')
                expanded, _, _ = decompress(raw[8:], length)
                if expanded[:4] not in (b'MDT\x03', b'MDT\x04'):
                    raise ValueError('Decompressed content is not MDT3/4')
                mids.append(expanded)
    spans.sort()
    if any((a + n > b for (a, n), (b, _) in zip(spans, spans[1:]))):
        raise ValueError('MI3 blocks overlap')
    if not mids:
        raise ValueError('No MID03 music resource found')
    return mids

def restore_ca02(ca):
    if len(ca) < 32 or ca[:4] != b'CA02' or struct.unpack_from('<I', ca, 4)[0] + 8 != len(ca):
        raise ValueError('Invalid CA02 audio resource')
    if ca[8] != 48:
        raise ValueError('Only verified CA02 0x30 / JA10 AAC is supported')
    count = struct.unpack_from('<H', ca, 28)[0]
    start = 32 + count * 8
    if start > len(ca):
        raise ValueError('CA02 index table is out of bounds')
    audio = bytearray(ca[start:])
    if len(audio) < 256 or audio[:3] != b'JA\x10':
        raise ValueError('Unsupported JA audio variant')
    for i in range(3, 256):
        audio[i] ^= -3 * i & 255
    p = frame = 0
    positions = {}
    while p + 7 <= len(audio):
        h = audio[p:p + 7]
        size = (h[3] & 3) << 11 | h[4] << 3 | h[5] >> 5
        if size < 7 or p + size > len(audio):
            break
        if frame:
            marker = 19 - 19 * frame & 255
            expected = bytes([marker, marker + 10 & 255, (marker & 252) - 4 & 255])
            if bytes(h[:3]) != expected:
                raise ValueError(f'Item {frame} frame uses an unverified descrambling mode')
        if h[3] & 192 != 128 or h[6] & 3:
            raise ValueError('Only single-block 44.1 kHz AAC-LC stereo frames are supported')
        positions[p] = frame
        audio[p:p + 3] = b'\xff\xf1P'
        p += size
        frame += 1
    if any(audio[p:]) or not frame:
        raise ValueError('Unparsed data remains at the end of an audio frame')
    for i in range(count):
        off, pcm = struct.unpack_from('<II', ca, 32 + i * 8)
        if positions.get(off) != 8 * i or pcm != i * 32768:
            raise ValueError('Index and audio frames do not match')
    return bytes(audio[:p])

def decode_pcm(aac):
    chunks = []
    with av.open(io.BytesIO(aac), format='aac') as container:
        resampler = av.AudioResampler(format='fltp', layout='stereo', rate=RATE)
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                chunks.append(converted.to_ndarray().T.copy())
        for converted in resampler.resample(None):
            chunks.append(converted.to_ndarray().T.copy())
    if not chunks:
        raise ValueError('AAC decoding produced no samples')
    return np.ascontiguousarray(np.concatenate(chunks), dtype=np.float32)

@dataclass
class MidiEvent:
    time: float
    port: int
    data: bytes
    order: int = 0
    track: int = -1
    shared: bool = False

@dataclass
class MidiPart:
    id: int
    name: str
    channels: str
    event_count: int
    note_count: int
    source_port: int = 0
    shared: bool = False

class TempoMap:

    def __init__(self, bpm_value, ppqn, changes):
        self.ppqn = ppqn
        self.ticks = [0]
        self.seconds = [0.0]
        self.bpms = [bpm_value]
        for tick, bpm in sorted(changes, key=lambda change: change[0]):
            elapsed = (tick - self.ticks[-1]) * 60000 / (self.bpms[-1] * ppqn)
            self.seconds.append(self.seconds[-1] + elapsed)
            self.ticks.append(tick)
            self.bpms.append(bpm)

    def seconds_at(self, tick):
        i = bisect.bisect_right(self.ticks, tick) - 1
        return self.seconds[i] + (tick - self.ticks[i]) * 60000 / (self.bpms[i] * self.ppqn)

@dataclass
class Variant:
    index: int
    mode: int
    selected: list
    starts: dict
    events: list
    duration: float
    bpm: float
    note_count: int
    warnings: list = field(default_factory=list)
    segmented: bool = False
    parts: list = field(default_factory=list)
    label: str = 'MDT'

def raw_messages(raw):
    p = 0
    while p < len(raw):
        status = raw[p]
        if status == 240:
            end = raw.find(b'\xf7', p + 1)
            if end < 0:
                raise ValueError('Incomplete SysEx')
            yield raw[p:end + 1]
            p = end + 1
        elif 128 <= status < 240:
            size = 2 if status >> 4 in (12, 13) else 3
            msg = raw[p:p + size]
            if len(msg) != size or any((v > 127 for v in msg[1:])):
                raise ValueError('Invalid MIDI message')
            yield msg
            p += size
        else:
            raise ValueError('MIDI payloads without a status byte are not supported')

def make_variant(data, index):
    streams = parse_streams(data)
    ppqn = {194: 48, 208: 480}.get(data[8])
    if ppqn is None:
        raise ValueError('Unknown time base')
    initial = struct.unpack_from('<I', data, 4)[0] or 120000
    changes = []
    warnings = set()
    starts = {}
    segmented = False
    for records in streams:
        for tick, kind, payload, _ in records:
            if kind == 2 and payload[:1] == b'\xe0' and (len(payload) >= 5):
                changes.append((tick, max(10000, min(237000, int.from_bytes(payload[1:5], 'little')))))
            elif kind == 2 and payload[:1] == b'\xe1':
                raise ValueError('An unsupported E1 tempo-ratio event was found; synchronization cannot be guaranteed')
            elif kind == 1 and len(payload) >= 2:
                if payload[0] == 21:
                    starts.setdefault(payload[1], tick)
                elif payload[0] == 20:
                    segmented = True
    tempo = TempoMap(initial, ppqn, changes)
    events = []
    voices = 16 if data[3] == 3 else 32
    count = 0
    end_tick = 0
    for stream, records in enumerate(streams):
        mapped = data[32 + stream] if stream < voices else None
        playable = mapped is not None and mapped < 32
        port, channel = divmod(mapped, 16) if playable else (0, 0)
        for tick, kind, payload, offset in records:
            end_tick = max(end_tick, tick)
            output = []
            if kind in (4, 5):
                try:
                    output = list(raw_messages(payload))
                except ValueError as ex:
                    warnings.add(str(ex))
                if not playable:
                    output = [m for m in output if m[0] == 240]
            elif kind == 6 and playable and (len(payload) == 1) and (payload[0] < 128):
                output = [bytes([192 | channel, payload[0]])]
            elif kind == 9 and playable and (len(payload) == 1) and (payload[0] < 128):
                output = [bytes([176 | channel, 7, payload[0]])]
            elif kind == 7 and playable and (len(payload) >= 3) and (max(payload[:2]) < 128):
                duration = int.from_bytes(payload[2:], 'little')
                if duration:
                    count += 1
                    output = [bytes([144 | channel, payload[0], payload[1]])]
                    events.append(MidiEvent(tempo.seconds_at(tick + duration), port, bytes([128 | channel, payload[0], 0]), -1, stream))
                    end_tick = max(end_tick, tick + duration)
            elif kind == 8 and len(payload) == 1 and (payload[0] < 128):
                v = payload[0]
                output = [bytes.fromhex('f041104212400004') + bytes([v, 60 - v & 127, 247])]
            for msg in output:
                if msg[0] != 240:
                    msg = bytes([msg[0] & 240 | channel]) + msg[1:]
                targets = (0, 1) if msg[0] == 240 and (not playable) else (port,)
                for dest in targets:
                    events.append(MidiEvent(tempo.seconds_at(tick), dest, msg, 1 if msg[0] >> 4 == 9 else 0, stream, len(targets) > 1))
    events.sort(key=lambda e: (e.time, e.order))
    selected = [v for v in data[10:20] if v != 255] if data[9] == 1 else []
    if segmented:
        warnings.add('Type-14 segmented audio detected: automatic audio scheduling is not supported')
    warnings.add('Auxiliary melody streams are not played; proprietary controls and original mixing are approximate')
    parts = []
    for stream in sorted({e.track for e in events}):
        own = [e for e in events if e.track == stream and (not (e.shared and e.port != 0))]
        shared = any((e.shared for e in own))
        channels = sorted({(e.data[0] & 15) + 1 for e in own if e.data[0] < 240})
        name = f'MDT track {stream + 1:02d}' if channels else f'Global setup track {stream + 1:02d}'
        parts.append(MidiPart(stream, name, ','.join(map(str, channels)) or 'SysEx', len(own), sum((e.data[0] >> 4 == 9 and e.data[2] > 0 for e in own)), own[0].port, shared))
    return Variant(index, data[9], selected, {i: tempo.seconds_at(t) for i, t in starts.items()}, events, tempo.seconds_at(end_tick), initial / 1000, count, sorted(warnings), segmented, parts)

@dataclass
class Song:
    mi3: Path
    sd3: Path | None
    variants: list
    pcm: list
    warnings: list

def load_song(mi3, sd3=None, progress=lambda message: None):
    mi3 = Path(mi3)
    progress('Unpacking MI3 music resources...')
    variants = [make_variant(d, i) for i, d in enumerate(read_mi3(mi3))]
    pcm = []
    warnings = []
    if sd3:
        sd3 = Path(sd3)
        data = sd3.read_bytes()
        if data[:4] != b'SD3D' or struct.unpack_from('<I', data, 4)[0] != 1:
            raise ValueError('SD3D version 1 is required')
        top = resources(data)
        if len(top) != 1 or top[0][:4] != b'SN3\x01':
            raise ValueError('A single SN3 version 1 resource is required')
        for i, ca in enumerate(resources(top[0])):
            progress(f'Decoding SD3 audio track {i}…')
            pcm.append(decode_pcm(restore_ca02(ca)))
        if mi3.stem.casefold() != sd3.stem.casefold():
            warnings.append('MI3 and SD3 filenames differ; verify that they belong to the same song')
    for variant in variants:
        missing = [i for i in variant.selected if i >= len(pcm)]
        if missing:
            warnings.append(f'MDT {variant.index} selects audio {missing}, but the matching SD3 was not provided')
    return Song(mi3, sd3, variants, pcm, warnings)
