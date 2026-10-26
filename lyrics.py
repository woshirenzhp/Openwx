"""Timed LRC/ASS text and conservative, untimed MI3 SNG text extraction."""
from dataclasses import dataclass, field
from pathlib import Path
import re
import struct
import json
import csv
import io
import math
NUMERIC_MARKER = re.compile('\\[[0-9]{4}\\]')

def clean_text(text):
    """Explicit filtering only; parsers always retain the source text."""
    return NUMERIC_MARKER.sub('', text)

@dataclass
class Cue:
    start: float
    end: float
    text: str
    spans: list = field(default_factory=list)
    sing_start: float | None = None
    timing_source: str = ''

def filter_cue(cue):
    """Return a filtered copy and remap span indices without changing timestamps."""
    removed = set()
    for match in NUMERIC_MARKER.finditer(cue.text):
        removed.update(range(match.start(), match.end()))
    prefix = [0]
    for index in range(len(cue.text)):
        prefix.append(prefix[-1] + (index not in removed))
    spans = [(a, b, prefix[l], prefix[r]) for a, b, l, r in cue.spans if 0 <= l <= r <= len(cue.text) and prefix[r] > prefix[l]]
    return Cue(cue.start, cue.end, clean_text(cue.text), spans, cue.sing_start, cue.timing_source)

def output_cues(cues, filter_numeric=False):
    return [filter_cue(c) for c in cues] if filter_numeric else list(cues)

def read_text(path):
    raw = Path(path).read_bytes()
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16')
    for encoding in ('utf-8-sig', 'cp932', 'gb18030'):
        try:
            return raw.decode(encoding)
        except UnicodeError:
            pass
    raise ValueError('Unrecognized lyric text encoding; save the file as UTF-8')

def stamp(value):
    minutes, cs = divmod(round(max(0, value) * 100), 6000)
    return f'[{minutes:02d}:{cs / 100:05.2f}]'

def lrc(text):
    tag = re.compile('\\[(\\d+):(\\d{1,2}(?:\\.\\d+)?)\\]')
    word = re.compile('<(\\d+):(\\d{1,2}(?:\\.\\d+)?)>')
    match = re.search('\\[offset:([+-]?\\d+)\\]', text, re.I)
    offset = int(match[1]) / 1000 if match else 0
    cues = []
    for line in text.splitlines():
        tags = list(tag.finditer(line))
        if not tags:
            continue
        body = line[tags[-1].end():].strip()
        words = list(word.finditer(body))
        plain = word.sub('', body)
        reference = int(tags[0][1]) * 60 + float(tags[0][2]) - offset
        for timestamp in tags:
            start = int(timestamp[1]) * 60 + float(timestamp[2]) - offset
            spans = []
            length = len(body[:words[0].start()]) if words else 0
            for i, marker in enumerate(words):
                end = words[i + 1].start() if i + 1 < len(words) else len(body)
                segment = body[marker.end():end]
                at = int(marker[1]) * 60 + float(marker[2]) - offset
                until = int(words[i + 1][1]) * 60 + float(words[i + 1][2]) - offset if i + 1 < len(words) else at + 1
                spans.append((at - reference, until - reference, length, length + len(segment)))
                length += len(segment)
            cues.append(Cue(start, start + 5, plain, spans))
    if not cues:
        raise ValueError('No LRC timestamps found; add timing marks or import timed lyrics first')
    cues.sort(key=lambda cue: cue.start)
    for i, cue in enumerate(cues):
        following = next((c.start for c in cues[i + 1:] if c.start > cue.start), cue.start + 5)
        cue.end = following
    return cues

def ass_time(text):
    h, m, s = text.strip().split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)

def ass(text):
    fields = None
    in_events = False
    events = []
    for line in text.splitlines():
        if line.startswith('['):
            in_events = line.strip().lower() == '[events]'
        if not in_events:
            continue
        if line.lower().startswith('format:'):
            fields = [name.strip().lower() for name in line.split(':', 1)[1].split(',')]
        if not line.lower().startswith('dialogue:') or not fields:
            continue
        if fields[-1] != 'text':
            raise ValueError('The last ASS Events field must be Text')
        values = line.split(':', 1)[1].lstrip().split(',', len(fields) - 1)
        if len(values) != len(fields):
            raise ValueError('Incomplete ASS Dialogue fields')
        row = dict(zip(fields, values))
        start, end = (ass_time(row['start']), ass_time(row['end']))
        body, spans, clock = ('', [], 0.0)
        pending = None
        for part in re.split('(\\{[^}]*\\})', row['text']):
            if part.startswith('{'):
                if re.search('\\\\r(?:[^\\\\}]*)', part):
                    pending = None
                for tag in re.finditer('\\\\(kt|kf|ko|k|K)(\\d+)', part):
                    value = int(tag[2]) / 100
                    if tag[1] == 'kt':
                        clock, pending = (value, None)
                    else:
                        pending = (clock, clock + value)
                        clock += value
                continue
            part = re.sub('\\\\([Nnh\\\\])', lambda m: {'N': '\n', 'n': '\n', 'h': ' ', '\\': '\\'}[m[1]], part)
            left = len(body)
            body += part
            if pending is not None and part:
                a, b = pending
                if spans and spans[-1][:2] == (a, b) and (spans[-1][3] == left):
                    spans[-1] = (a, b, spans[-1][2], len(body))
                else:
                    spans.append((a, b, left, len(body)))
        if end > start and body:
            position = re.search('\\\\pos\\(\\s*([+-]?[\\d.]+)\\s*,\\s*([+-]?[\\d.]+)\\s*\\)', row['text'])
            alignment = re.search('\\\\an([1-9])', row['text'])
            key = None
            if position and spans and ('\n' not in body) and (not re.search('\\\\(?:move|t|p\\d)\\b', row['text'])):
                x, y = map(float, position.groups())
                key = (start, end, round(y, 3), alignment[1] if alignment else None, *(row.get(k, '') for k in ('layer', 'marked', 'style', 'name', 'effect', 'marginl', 'marginr', 'marginv')))
            events.append((key, float(position[1]) if position else 0, Cue(start, end, body, spans)))
    groups = {}
    for index, (key, x, cue) in enumerate(events):
        if key is not None:
            groups.setdefault(key, []).append(index)
    merged, skipped = ({}, set())
    for indices in groups.values():
        if len(indices) < 2 or len({events[i][1] for i in indices}) != len(indices):
            continue
        body, spans = ('', [])
        for i in sorted(indices, key=lambda i: events[i][1]):
            cue = events[i][2]
            spans.extend(((a, b, left + len(body), right + len(body)) for a, b, left, right in cue.spans))
            body += cue.text
        cue = events[indices[0]][2]
        merged[indices[0]] = Cue(cue.start, cue.end, body, spans, timing_source='ass-positioned-karaoke')
        skipped.update(indices[1:])
    cues = [merged.get(i, event[2]) for i, event in enumerate(events) if i not in skipped]
    if not cues:
        raise ValueError('No valid ASS Dialogue events found')
    return sorted(cues, key=lambda cue: cue.start)

def load(path):
    from subtitle_formats import SUFFIXES, load as load_subtitle
    if Path(path).suffix.lower() in SUFFIXES:
        return load_subtitle(path)
    if Path(path).suffix.lower() == '.csv':
        data = {'lines': list(csv.DictReader(io.StringIO(read_text(path))))}
        cues = [Cue(float(row['display_seconds']), float(row['clear_seconds']), row['text'], spans=json.loads(row.get('spans_json') or '[]'), sing_start=float(row['sing_seconds']), timing_source=row.get('timing_source', '')) for row in data['lines']]
        if not cues or any((not c.start <= c.sing_start <= c.end for c in cues)):
            raise ValueError('CSV requires valid display_seconds / sing_seconds / clear_seconds / text fields')
        return sorted(cues, key=lambda c: c.start)
    if Path(path).suffix.lower() == '.json':
        data = json.loads(read_text(path))
        return [Cue(float(row['display_seconds']), float(row['clear_seconds']), row['text'], spans=row.get('spans', []), sing_start=float(row['sing_seconds']), timing_source=row.get('timing_source', '')) for row in data['lines']]
    return ass(read_text(path)) if Path(path).suffix.lower() in ('.ass', '.ssa') else lrc(read_text(path))

def mi3_timing(path, resource=0):
    from song import resources
    data = Path(path).read_bytes()
    if len(data) < 48 or data[:4] != b'MIDI' or struct.unpack_from('<I', data, 4)[0] != 3:
        raise ValueError('Select an MI3 file')
    block = None
    for i in range(5):
        off, size = struct.unpack_from('<II', data, 8 + 8 * i)
        if off + size > len(data):
            raise ValueError('MI3 block is out of bounds')
        if data[off:off + 4] == b'SNG\x04':
            block = data[off:off + size]
    if block is None:
        raise ValueError('No supported SNG04 lyric resource found')
    items = resources(block)
    if not 0 <= resource < len(items):
        raise ValueError('Lyric resource index is out of range')
    item = items[resource]
    if len(item) < 40:
        raise ValueError('Incomplete SNG header')
    text_start, line_table, color_table = struct.unpack_from('<HHH', item)
    if not 40 <= text_start < line_table < color_table < len(item):
        raise ValueError('Invalid SNG table offsets')
    count = struct.unpack_from('<H', item, line_table)[0]
    colors = struct.unpack_from('<H', item, color_table)[0]
    if line_table + 8 + count * 16 != color_table or color_table + 8 + colors * 8 != len(item):
        raise ValueError('Unsupported SNG timing-table layout')
    lines = []
    for index in range(count):
        mode, reserved, relative, display, sing, clear = struct.unpack_from('<BBHIII', item, line_table + 8 + index * 16)
        pos = text_start + relative
        if pos + 16 > line_table:
            raise ValueError('SNG text index is out of bounds')
        size = struct.unpack_from('<I', item, pos)[0]
        glyph_count = item[pos + 14]
        if size < 16 + 2 * glyph_count or pos + size > line_table or (not display <= sing <= clear):
            raise ValueError('Invalid SNG text or line timing')
        text = ''
        unresolved = []
        for p in range(pos + 16, pos + 16 + 2 * glyph_count, 2):
            a, b = item[p:p + 2]
            try:
                if a in (160, 161, 163):
                    ch = bytes((130, b + 126)).decode('cp932')
                    if a in (161, 163):
                        ch = ''.join((chr(ord(c) + 96) if 'ぁ' <= c <= 'ゖ' else c for c in ch))
                elif a == 1:
                    ch = f'[{a:02X}{b:02X}]'
                    unresolved.append(ch)
                elif a == 168 and 32 <= b <= 126:
                    ch = chr(b)
                else:
                    ch = bytes((a, b)).decode('cp932')
            except (ValueError, UnicodeError):
                ch = f'[{a:02X}{b:02X}]'
                unresolved.append(ch)
            text += ch
        lines.append({'index': index, 'text_offset': pos, 'text': text, 'mode': mode, 'font_id': item[pos + 15], 'reserved': reserved, 'display_cs': display, 'sing_cs': sing, 'clear_cs': clear, 'display_seconds': display / 100, 'sing_seconds': sing / 100, 'clear_seconds': clear / 100, 'glyphs_hex': item[pos + 16:pos + 16 + 2 * glyph_count].hex(), 'unresolved_codes': unresolved})
    if not lines:
        raise ValueError('No lyric text could be extracted')
    changes = []
    for index in range(colors):
        time, command, multiplier, speed = struct.unpack_from('<IBBH', item, color_table + 8 + index * 8)
        changes.append({'time_cs': time, 'command': command, 'multiplier': multiplier, 'speed_raw': speed})
    return {'format': 'mi3-sng04-timing-v1', 'source': str(Path(path)), 'resource': resource, 'time_unit': 'centisecond', 'text_start': text_start, 'line_table_offset': line_table, 'color_table_offset': color_table, 'lines': lines, 'color_changes': changes, 'notes': ['Line display, highlight-start and clear times were verified against firmware; they are not evenly distributed estimates.', 'Unknown glyphs retain hexadecimal placeholders. Narrow ASCII glyphs are displayed as text; widths differ from the original device.', 'The color-change table is preserved; exact original pixel/character highlight geometry is not reproduced.']}

def mi3_text(path, resource=0):
    return '\n'.join((row['text'] for row in mi3_timing(path, resource)['lines']))

def character_template(data):
    """Estimate character boundaries from verified speed events, normalized to font widths.

    Original FONTxx metrics are unavailable: this is an editable template, not an
    exact recreation of the device's pixel geometry or character timestamps.
    """
    import unicodedata
    from lyric_clock import SweepClock, centiseconds
    font = None
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(str(Path(__file__).parent / 'fonts' / 'UDRGMZtk.ttf'), 48)
    except (OSError, ImportError):
        pass
    cues = []
    for row_index, row in enumerate(data['lines']):
        start_cs = centiseconds(row, 'display')
        begin_cs = centiseconds(row, 'sing')
        end_cs = centiseconds(row, 'clear')
        start, begin, end = (start_cs / 100, begin_cs / 100, end_cs / 100)
        lane = row['mode']
        following = [centiseconds(r, 'sing') for r in data['lines'][row_index + 1:] if r['mode'] == lane and centiseconds(r, 'sing') > begin_cs]
        limit_cs = min([end_cs] + following)
        try:
            clock = SweepClock(data['color_changes'], begin_cs, limit_cs, lane)
        except ValueError as ex:
            raise ValueError('Invalid lyric sweep data or clock outside the verified range: ' + str(ex)) from ex
        distance = clock.distance
        limit = limit_cs / 100
        text = row['text']
        widths = []
        for char in text:
            width = font.getlength(char) if font else 48 if unicodedata.east_asian_width(char) in 'WF' else 24
            widths.append(max(1, width) if char != '\n' else 0)
        for match in re.finditer('\\[[0-9A-Fa-f]{4}\\]', text):
            widths[match.start():match.end()] = [48 / 6] * 6
        total = sum(widths)
        spans, cursor = ([], 0)
        source = ('estimated-speed-font-v2-cs' if font else 'estimated-speed-width-v2-cs') if distance else 'estimated-width-fallback-v2'
        last_end = begin_cs
        if total and limit > begin:
            for index, width in enumerate(widths):
                if not width:
                    continue
                if distance:
                    a_cs = max(last_end, clock.last_before_motion(cursor / total * distance))
                    cursor += width
                    b_cs = max(a_cs, clock.first_reached(cursor / total * distance))
                    last_end = b_cs
                    a, b = (a_cs / 100, b_cs / 100)
                else:
                    a = begin + (limit - begin) * cursor / total
                    cursor += width
                    b = begin + (limit - begin) * cursor / total
                spans.append((round(a - start, 6), round(b - start, 6), index, index + 1))
        cues.append(Cue(start, end, text, spans, begin, source))
    return cues

def mi3_cues(path, resource=0):
    return character_template(mi3_timing(path, resource))

def save_cues(path, cues, filter_numeric=False):
    """Save edited line/character timing; JSON/CSV retain every span at millisecond precision."""
    from subtitle_formats import SUFFIXES, save as save_subtitle
    if Path(path).suffix.lower() in SUFFIXES:
        return save_subtitle(path, output_cues(cues, filter_numeric))
    rows = []
    for index, cue in enumerate(output_cues(cues, filter_numeric)):
        cue = Cue(cue.start, cue.end, cue.text, list(cue.spans), cue.sing_start, cue.timing_source)
        sing = cue.sing_start if cue.sing_start is not None else cue.start
        if not all((math.isfinite(v) for v in (cue.start, sing, cue.end))) or not cue.start <= sing <= cue.end:
            raise ValueError(f'Line {index + 1} has invalid timing')
        rows.append({'index': index, 'display_seconds': cue.start, 'sing_seconds': sing, 'clear_seconds': cue.end, 'text': cue.text, 'spans': cue.spans, 'timing_source': cue.timing_source})
    path = Path(path)
    if path.suffix.lower() == '.json':
        path.write_text(json.dumps({'format': 'lyric-timeline-v1', 'time_unit': 'second', 'lines': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
    elif path.suffix.lower() == '.csv':
        with path.open('w', encoding='utf-8-sig', newline='') as out:
            writer = csv.DictWriter(out, fieldnames=['index', 'display_seconds', 'sing_seconds', 'clear_seconds', 'text', 'spans_json', 'timing_source'])
            writer.writeheader()
            for row in rows:
                writer.writerow({k: v for k, v in row.items() if k != 'spans'} | {'spans_json': json.dumps(row['spans'], ensure_ascii=False)})
    elif path.suffix.lower() == '.lrc':
        path.write_text('\n'.join((stamp(r['sing_seconds']) + r['text'].replace('\n', ' ') for r in rows)) + '\n', encoding='utf-8')
    else:
        raise ValueError('Select a JSON, CSV or LRC file')

def protect_source(path, song):
    if song:
        destination = Path(path).resolve()
        if any((source and destination == Path(source).resolve() for source in (song.mi3, song.sd3))):
            raise ValueError('Lyric export cannot overwrite the current music or audio source; choose a new filename')

def export_template(path, folder, resource=0, filter_numeric=False):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    data = mi3_timing(path, resource)
    for row, cue in zip(data['lines'], character_template(data)):
        if filter_numeric:
            cue = filter_cue(cue)
        row['spans'] = cue.spans
        row['timing_source'] = cue.timing_source
    data['notes'].append('Default character times are estimated from the sweep-speed curve normalized to substitute font widths; they are not original device timestamps.')
    data['character_timing'] = {'algorithm': 'firmware-clock-font-v2', 'native_clock_hz': 100, 'span_time_unit': 'seconds relative to display_seconds', 'estimated': True, 'font_metrics': 'substitute'}
    data['filter_numeric_markers'] = bool(filter_numeric)
    if filter_numeric:
        for row in data['lines']:
            row['text'] = clean_text(row['text'])
    stem = Path(path).stem + f'_lyrics_{resource:02d}'
    outputs = [folder / (stem + suffix) for suffix in ('.json', '.csv', '.lrc', '.ass')]
    if any((p.exists() for p in outputs)):
        raise ValueError('Timing templates already exist; select a new output folder')
    outputs[0].write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    with outputs[1].open('w', encoding='utf-8-sig', newline='') as out:
        fields = ['index', 'display_seconds', 'sing_seconds', 'clear_seconds', 'text', 'spans_json', 'timing_source']
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows((dict(row, spans_json=json.dumps(row['spans'])) for row in data['lines']))
    outputs[2].write_text('[re:MI3 template; LRC timestamps use sing/start-color time]\n' + '\n'.join((stamp(row['sing_seconds']) + row['text'] for row in data['lines'])) + '\n', encoding='utf-8')

    def at(seconds):
        cs = round(seconds * 100)
        return f'{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}'
    header = '[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Microsoft YaHei,54,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,3,0,2,30,30,50,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    events = []
    for row in data['lines']:
        text = row['text'].replace('{', '｛').replace('}', '｝').replace('\n', '\\N')
        if row['sing_seconds'] > row['display_seconds']:
            events.append(f"Dialogue: 0,{at(row['display_seconds'])},{at(row['sing_seconds'])},Default,,0,0,0,,{text}")
        events.append(f"Dialogue: 0,{at(row['sing_seconds'])},{at(row['clear_seconds'])},Default,,0,0,0,,{{\\c&H00FFFF&}}{text}")
    outputs[3].write_text(header + '\n'.join(events) + '\n', encoding='utf-8')
    return outputs
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Export verified SNG04 line timing to JSON/CSV/LRC/ASS')
    parser.add_argument('mi3', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resource', type=int, default=0)
    parser.add_argument('--filter-numeric-markers', action='store_true', help='Remove [0000] through [9999] from output text')
    args = parser.parse_args()
    for output in export_template(args.mi3, args.output, args.resource, args.filter_numeric_markers):
        print(output)
