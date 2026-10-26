"""Merge tracks from multiple SMF type 0/1 files on a common seconds timeline."""
from pathlib import Path
import bootstrap
from song import MidiEvent, MidiPart, Song, Variant

def load_smf_song(paths, progress=lambda text: None):
    import mido
    paths = [Path(p) for p in paths]
    if not paths:
        raise ValueError('Select at least one SMF file')
    events, parts, warnings = ([], [], [])
    duration = 0.0
    total_notes = 0
    for path in paths:
        progress(f'Loading SMF: {path.name}')
        midi = mido.MidiFile(path)
        if midi.type not in (0, 1):
            raise ValueError(f'{path.name}: asynchronous SMF type 2 is not supported')
        if midi.ticks_per_beat <= 0:
            raise ValueError(f'{path.name}: SMPTE time division is not supported')
        raw, tempos = ([], [])
        file_end = 0
        base = len(parts)
        for index, track in enumerate(midi.tracks):
            tick = 0
            port = 0
            name = track.name or f'Track {index + 1}'
            own = []
            for order, msg in enumerate(track):
                tick += msg.time
                file_end = max(file_end, tick)
                if msg.type == 'set_tempo':
                    if msg.tempo <= 0:
                        raise ValueError(f'{path.name}: tempo must be greater than 0')
                    tempos.append((tick, index, order, msg.tempo))
                elif msg.type == 'midi_port':
                    port = msg.port
                elif not msg.is_meta:
                    if msg.type not in ('sysex', 'note_on', 'note_off', 'polytouch', 'control_change', 'program_change', 'aftertouch', 'pitchwheel'):
                        raise ValueError(f'{path.name}: unsupported SMF message {msg.type}')
                    own.append((tick, order, port, bytes(msg.bytes())))
            channels = sorted({(d[0] & 15) + 1 for _, _, _, d in own if d[0] < 240})
            notes = sum((d[0] >> 4 == 9 and d[2] > 0 for _, _, _, d in own))
            parts.append(MidiPart(base + index, f'{path.name} / {index + 1}: {name}', ','.join(map(str, channels)) or 'Setup / tempo', len(own), notes, own[0][2] if own else 0))
            total_notes += notes
            raw.extend(((tick, index, order, port, data) for tick, order, port, data in own))
        from bisect import bisect_right
        ticks, seconds, values = ([0], [0.0], [500000])
        for tick, _, _, tempo in sorted(tempos):
            seconds.append(seconds[-1] + (tick - ticks[-1]) * values[-1] / (midi.ticks_per_beat * 1000000.0))
            ticks.append(tick)
            values.append(tempo)

        def at(tick):
            i = bisect_right(ticks, tick) - 1
            return seconds[i] + (tick - ticks[i]) * values[i] / (midi.ticks_per_beat * 1000000.0)
        for tick, index, order, port, data in sorted(raw):
            events.append(MidiEvent(at(tick), port, data, order, base + index))
        duration = max(duration, at(file_end))
    events.sort(key=lambda event: event.time)
    from xf_lyrics import read_midi
    lyric_cues, lyric_source, lyric_warnings = ([], '', [])
    for path in paths:
        try:
            found = read_midi(path)
            if found:
                lyric_cues, lyric_source = (found, path.name)
                duration = max(duration, max((c.end for c in found)))
                break
        except (ValueError, OSError, EOFError, UnicodeError) as ex:
            lyric_warnings.append('MIDI lyric import: ' + str(ex))
    if not events and (not lyric_cues):
        raise ValueError('The selected SMF files contain no playable MIDI messages')
    duration = max(duration, 1 / 44100)
    if len(paths) > 1:
        warnings.append('SMF files start at the same time and retain their own tempo maps; song durations are not automatically aligned.')
    warnings.append('Original SMF channels are preserved. Tracks on the same port/channel share programs and controllers; use separate ports for independent sounds.')
    variant = Variant(0, 0, [], {}, events, duration, 0, total_notes, warnings, parts=parts, label='SMF')
    return Song(paths[0], None, [variant], [], lyric_warnings, lyric_cues=lyric_cues, lyric_source=lyric_source, music_paths=paths)
