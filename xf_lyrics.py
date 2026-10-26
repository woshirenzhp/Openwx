"""Yamaha XF / SMF lyrics. XF v2.01 sections 1, 3, 4 and appendix A.

MIDI lyric events give syllable starts, not native per-character end times.
The next event/break bounds a syllable; this provenance is retained in Cue.
"""
from bisect import bisect_right
from pathlib import Path
import io
import re
import struct
import bootstrap
import mido
CODECS = {'L1': 'latin1', 'LATIN': 'latin1', 'JP': 'shift_jis', 'HZ': 'hz', 'B5': 'big5', 'CY': 'koi8_r', 'KR': 'iso2022_kr', 'UNICODE': 'utf-8', 'UTF-8': 'utf-8'}

def chunk_tracks(raw, division):
    """Read XFKM streams following normal SMF chunks, using the SMF timebase."""
    result, pos = ([], 0)
    while pos < len(raw):
        if pos + 8 > len(raw):
            raise ValueError('Truncated MIDI/XF chunk header')
        kind, size = (raw[pos:pos + 4], struct.unpack_from('>I', raw, pos + 4)[0])
        payload = raw[pos + 8:pos + 8 + size]
        if len(payload) != size:
            raise ValueError('Truncated MIDI/XF chunk')
        if kind == b'XFKM':
            header = b'MThd' + struct.pack('>IHHH', 6, 0, 1, division)
            wrapped = header + b'MTrk' + struct.pack('>I', size) + payload
            result.append(mido.MidiFile(file=io.BytesIO(wrapped), charset='latin1').tracks[0])
        pos += 8 + size
    return result

def read_midi(path):
    from lyrics import Cue
    raw = Path(path).read_bytes()
    midi = mido.MidiFile(file=io.BytesIO(raw), charset='latin1')
    if midi.type not in (0, 1) or midi.ticks_per_beat <= 0:
        raise ValueError('MIDI lyrics require SMF type 0/1 with PPQN timing')
    tracks = []
    tempos, file_end = ([(0, -1, -1, 500000)], 0)
    for ti, track in enumerate(midi.tracks):
        tick, timed = (0, [])
        for order, msg in enumerate(track):
            tick += msg.time
            timed.append((tick, msg))
            if msg.type == 'set_tempo':
                if msg.tempo <= 0:
                    raise ValueError('Invalid MIDI tempo')
                tempos.append((tick, ti, order, msg.tempo))
        file_end = max(file_end, tick)
        tracks.append(timed)
    ticks, seconds, rates = ([], [], [])
    previous, elapsed, tempo = (0, 0.0, 500000)
    for tick, _, _, value in sorted(tempos):
        elapsed += (tick - previous) * tempo / midi.ticks_per_beat / 1000000.0
        ticks.append(tick)
        seconds.append(elapsed)
        rates.append(value)
        previous, tempo = (tick, value)

    def at(tick):
        tick = max(0, tick)
        i = bisect_right(ticks, tick) - 1
        return seconds[i] + (tick - ticks[i]) * rates[i] / midi.ticks_per_beat / 1000000.0
    extra = []
    for track in chunk_tracks(raw, midi.ticks_per_beat):
        tick, timed = (0, [])
        for msg in track:
            tick += msg.time
            timed.append((tick, msg))
        file_end = max(file_end, tick)
        extra.append(timed)
    candidates = extra + tracks
    header = next((msg.text for track in candidates for _, msg in track if msg.type == 'cue_marker' and '$Lyrc:' in msg.text), '')

    def options(text):
        fields = text.strip('<>').split(':')
        if len(fields) < 4 or fields[0] != '$Lyrc':
            raise ValueError('Invalid XF $Lyrc header')
        code = fields[3].upper()
        if code not in CODECS:
            raise ValueError('Unsupported XF character code: ' + code)
        return (CODECS[code], int(fields[2]))
    default_codec, default_offset = options(header) if header else (None, 0)
    result = []
    for track in candidates:
        codec, offset, xf = (default_codec, default_offset, bool(header))
        lyric_events = [msg for _, msg in track if msg.type == 'lyrics']
        kar = not lyric_events and any((msg.type == 'text' and (msg.text.startswith('@KMIDI') or '/' in msg.text or '\\' in msg.text) for _, msg in track))
        line, syllables, cues = ('', [], [])

        def finish(end):
            nonlocal line, syllables
            if line and syllables:
                start = syllables[0][0]
                end = max(start + 0.001, end)
                spans = []
                for i, (when, left, right) in enumerate(syllables):
                    until = syllables[i + 1][0] if i + 1 < len(syllables) else end
                    spans.append((when - start, max(when, until) - start, left, right))
                cues.append(Cue(start, end, line, spans, start, 'midi-syllable-next-event'))
            line, syllables = ('', [])
        for tick, msg in track:
            if msg.type == 'cue_marker' and '$Lyrc:' in msg.text:
                codec, offset = options(msg.text)
                xf = True
            if msg.type != 'lyrics' and (not (kar and msg.type == 'text')):
                continue
            data = msg.text.encode('latin1')
            suggested = re.match(b'\\{@([^}]+)\\}', data)
            if suggested:
                name = suggested[1].decode('ascii').upper()
                if name not in CODECS:
                    raise ValueError('Unsupported MIDI lyric encoding: ' + name)
                codec = CODECS[name]
                data = data[suggested.end():]
            if data.startswith((b'\xff\xfe', b'\xfe\xff')):
                text = data.decode('utf-16')
            elif codec:
                text = data.decode(codec)
            else:
                for encoding in ('utf-8', 'cp932', 'latin1'):
                    try:
                        text = data.decode(encoding)
                        break
                    except UnicodeError:
                        continue
            if text.startswith(('@', '{#')):
                continue
            when = at(tick - offset)
            pieces = re.findall('\\\\.|[^\\\\]|\\\\$', text, re.S)
            pending = ''

            def append():
                nonlocal pending, line
                if pending:
                    left = len(line)
                    line += pending
                    syllables.append((when, left, len(line)))
                    pending = ''
            for piece in pieces:
                escaped = piece.startswith('\\') and len(piece) == 2
                if escaped:
                    value = {'r': '\r', 'n': '\n', 't': '\t'}.get(piece[1], piece[1])
                else:
                    value = piece
                is_break = value in ('\r', '\n') or (not escaped and (xf and value in ('/', '%', '<') or (kar and value in ('/', '\\'))))
                if is_break:
                    append()
                    finish(when)
                elif not escaped and xf and (value == '^'):
                    pending += ' '
                else:
                    pending += value
            append()
        last = syllables[-1][0] if syllables else 0
        finish(max(at(file_end - default_offset), last + 2))
        if cues:
            result = cues
            break
    return sorted(result, key=lambda c: c.start)

def write_midi(path, cues):
    """Write a lyric-only XF02 SMF type 0; never modify a source MIDI file."""
    text = ''.join((c.text for c in cues))
    encoding, code = ('utf-16', 'L1')
    for candidate, symbol in [('latin1', 'L1'), ('shift_jis', 'JP'), ('hz', 'HZ'), ('big5', 'B5'), ('koi8_r', 'CY')]:
        try:
            text.encode(candidate)
            encoding, code = (candidate, symbol)
            break
        except UnicodeError:
            pass
    midi = mido.MidiFile(type=0, ticks_per_beat=480, charset='latin1')
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=500000))
    track.append(mido.MetaMessage('sequencer_specific', data=bytes.fromhex('43 7b 00 58 46 30 32 00 10')))
    track.append(mido.MetaMessage('cue_marker', text=f'$Lyrc:1:0:{code}'))
    events = []

    def emit(when, value, priority):
        escaped = ''.join(('\\' + c if c in '\\/^%<{}[]' else c for c in value))
        events.append((round(when * 960), priority, mido.MetaMessage('lyrics', text=escaped.encode(encoding).decode('latin1'))))
    ordered = sorted(cues, key=lambda c: c.sing_start if c.sing_start is not None else c.start)
    for i, cue in enumerate(ordered):
        begin = cue.sing_start if cue.sing_start is not None else cue.start
        stop = min(cue.end, ordered[i + 1].sing_start if ordered[i + 1].sing_start is not None else ordered[i + 1].start) if i + 1 < len(ordered) else cue.end
        if stop <= begin:
            raise ValueError('XF lyrics cannot represent overlapping syllable lines')
        if cue.spans:
            cursor, previous = (0, -1)
            for index, (a, b, left, right) in enumerate(cue.spans):
                if left < cursor or not left <= right <= len(cue.text):
                    raise ValueError('XF export needs ordered syllable spans; use JSON for arbitrary spans')
                if cue.start + a >= stop or a < previous:
                    raise ValueError('XF export has overlapping syllables; use TTML or JSON')
                tail = cue.text[right:] if index == len(cue.spans) - 1 else ''
                emit(max(0, cue.start + a), (cue.text[cursor:right] + tail).replace('\n', ' '), 1)
                cursor, previous = (right, a)
        else:
            emit(max(0, begin), cue.text.replace('\n', ' '), 1)
        events.append((round(max(0, stop) * 960), 0, mido.MetaMessage('lyrics', text='/')))
    previous = 0
    for tick, _, message in sorted(events, key=lambda e: (e[0], e[1])):
        track.append(message.copy(time=tick - previous))
        previous = tick
    midi.save(path)
