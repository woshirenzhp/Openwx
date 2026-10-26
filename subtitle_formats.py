"""Subtitle interchange: text/timing only; player style is applied separately."""
from pathlib import Path
import html
import math
import re
import textwrap
import xml.etree.ElementTree as ET
IMPORT_PATTERN = '*.lrc *.xf *.mid *.midi *.kar *.srt *.vtt *.ass *.ssa *.ttml *.dfxp *.scc *.json *.csv'
EXPORT_TYPES = [('JSON', '*.json'), ('CSV', '*.csv'), ('LRC', '*.lrc'), ('XF / MIDI', '*.xf'), ('SRT', '*.srt'), ('WebVTT', '*.vtt'), ('ASS', '*.ass'), ('SSA', '*.ssa'), ('TTML', '*.ttml'), ('DFXP', '*.dfxp'), ('SCC / CEA-608', '*.scc')]
SUFFIXES = {'.xf', '.mid', '.midi', '.kar', '.srt', '.vtt', '.ass', '.ssa', '.ttml', '.dfxp', '.scc'}
TT = 'http://www.w3.org/ns/ttml'
TP = TT + '#parameter'
XML = 'http://www.w3.org/XML/1998/namespace'

def clock(value, sep='.'):
    ms = round(max(0, value) * 1000)
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}'

def parse_clock(text):
    pieces = text.replace(',', '.').split(':')
    if len(pieces) not in (2, 3):
        raise ValueError('Invalid subtitle timestamp: ' + text)
    return sum((float(v) * 60 ** i for i, v in enumerate(reversed(pieces))))

def plain(text):
    text = re.sub('<br\\s*/?>', '\n', text, flags=re.I)
    return html.unescape(re.sub('</?(?:b|i|u|s|c|v|lang|ruby|rt)(?:[ .][^>]*)?>', '', text, flags=re.I))

def read_blocks(text, vtt=False):
    from lyrics import Cue
    rows = []
    for block in re.split('\\n[ \\t]*\\n', text.replace('\r\n', '\n').replace('\r', '\n').strip()):
        lines = block.splitlines()
        if not lines or (vtt and re.match('^(NOTE(?:\\s|$)|STYLE$|REGION$)', lines[0])):
            continue
        i = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if i is None:
            continue
        match = re.match('\\s*(\\S+)\\s+-->\\s+(\\S+)', lines[i])
        if not match:
            raise ValueError('Invalid subtitle cue timing')
        start, end = map(parse_clock, match.groups())
        body, spans = ('\n'.join(lines[i + 1:]), [])
        if vtt:
            parts = re.split('<((?:\\d+:)?\\d{2}:\\d{2}\\.\\d{3})>', body)
            if len(parts) > 1:
                body, when = ('', start)
                for j in range(0, len(parts), 2):
                    piece = plain(parts[j])
                    until = parse_clock(parts[j + 1]) if j + 1 < len(parts) else end
                    if not start <= when <= until <= end:
                        raise ValueError('WebVTT inline timestamps must be ordered inside the cue')
                    if piece:
                        spans.append((when - start, until - start, len(body), len(body) + len(piece)))
                        body += piece
                    when = until
            else:
                body = plain(body)
        else:
            body = plain(body)
        rows.append(Cue(start, end, body, spans, timing_source='webvtt-inline' if spans else 'subtitle-line'))
    return checked(rows)

def checked(cues):
    if not cues:
        raise ValueError('No timed lyrics were found')
    for cue in cues:
        if not all((math.isfinite(x) for x in (cue.start, cue.end))) or not 0 <= cue.start < cue.end:
            raise ValueError('Subtitle times must be finite, nonnegative, with end after start')
        for a, b, left, right in cue.spans:
            if not (math.isfinite(a) and math.isfinite(b) and (0 <= a <= b <= cue.end - cue.start + 1e-06) and isinstance(left, int) and isinstance(right, int) and (0 <= left <= right <= len(cue.text))):
                raise ValueError('Invalid subtitle syllable/character span')
    return sorted(cues, key=lambda c: c.start)

def read_ttml(text):
    from lyrics import Cue
    root = ET.fromstring(text)
    params = {key.rsplit('}', 1)[-1]: value for key, value in root.attrib.items()}
    rate = float(params.get('frameRate', '30'))
    multiplier = params.get('frameRateMultiplier', '1 1').split()
    rate *= float(multiplier[0]) / float(multiplier[1])
    sub = float(params.get('subFrameRate', '1'))
    tick = float(params.get('tickRate', str(rate * sub)))
    if min(rate, sub, tick) <= 0 or not all((math.isfinite(x) for x in (rate, sub, tick))):
        raise ValueError('Invalid TTML frame/tick rate')
    if params.get('dropMode', 'nonDrop') != 'nonDrop':
        raise ValueError('TTML drop-frame clock expressions are not supported; use media-time seconds')

    def time(s):
        if ':' in s:
            parts = s.split(':')
            if len(parts) == 4:
                f = parts.pop().split('.')
                fraction = (float(f[0]) + (float(f[1]) / sub if len(f) > 1 else 0)) / rate
                return parse_clock(':'.join(parts)) + fraction
            return parse_clock(s)
        m = re.fullmatch('([+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+))(h|m|s|ms|f|t)', s)
        if not m:
            raise ValueError('Unsupported TTML time expression: ' + s)
        return float(m[1]) * {'h': 3600, 'm': 60, 's': 1, 'ms': 0.001, 'f': 1 / rate, 't': 1 / tick}[m[2]]

    def interval(node, base, limit):
        begin = base + time(node.get('begin', '0s'))
        end = min(limit, base + time(node.get('end'))) if node.get('end') else limit
        if node.get('dur'):
            end = min(end, begin + time(node.get('dur')))
        return (begin, end)
    cues = []

    def visit(node, base, limit, preserve=False):
        begin, end = interval(node, base, limit)
        preserve = node.get('{' + XML + '}space', 'preserve' if preserve else 'default') == 'preserve'
        tag = node.tag.rsplit('}', 1)[-1]
        if tag == 'p':
            body, spans = ('', [])

            def add(value):
                nonlocal body
                body += value if preserve else re.sub('\\s+', ' ', value)

            def content(parent, a, b, inherited_timed=False):
                add(parent.text or '')
                sequential, cursor = (parent.get('timeContainer') == 'seq', a)
                for child in parent:
                    ca, cb = interval(child, cursor if sequential else a, b)
                    left = len(body)
                    if child.tag.rsplit('}', 1)[-1] == 'br':
                        body_break()
                    else:
                        timed = any((key in child.attrib for key in ('begin', 'end', 'dur')))
                        before = len(spans)
                        content(child, ca, cb, inherited_timed or timed)
                        if timed and len(body) > left and (len(spans) == before):
                            spans.append((ca - begin, cb - begin, left, len(body)))
                    add(child.tail or '')
                    if sequential:
                        cursor = cb

            def body_break():
                nonlocal body
                body += '\n'
            content(node, begin, end)
            if not preserve:
                leading = len(body) - len(body.lstrip())
                body = body.strip()
                spans = [(a, b, max(0, l - leading), min(len(body), r - leading)) for a, b, l, r in spans if r > leading and l - leading < len(body)]
            if not math.isfinite(end):
                finite_ends = [begin + b for a, b, l, r in spans if math.isfinite(b)]
                if not finite_ends:
                    raise ValueError('TTML paragraph needs an end, duration or finite timed spans')
                end = max(finite_ends)
            spans = [(round(max(0, a), 9), round(min(b, end - begin), 9), l, r) for a, b, l, r in spans]
            cues.append(Cue(begin, end, body, spans, timing_source='ttml-span' if spans else 'ttml-line'))
            return
        cursor = begin
        for child in node:
            visit(child, cursor if node.get('timeContainer') == 'seq' else begin, end, preserve)
            if node.get('timeContainer') == 'seq':
                cursor = interval(child, cursor, end)[1]
    visit(root, 0, float('inf'))
    return checked(cues)

def read_scc(text):
    from scc_lyrics import read
    return checked(read(text))

def load(path):
    from lyrics import read_text, ass
    suffix = Path(path).suffix.lower()
    if suffix in ('.xf', '.mid', '.midi', '.kar'):
        from xf_lyrics import read_midi
        return checked(read_midi(path))
    text = read_text(path)
    if suffix in ('.ass', '.ssa'):
        return checked(ass(text))
    if suffix in ('.srt', '.vtt'):
        return read_blocks(text, suffix == '.vtt')
    if suffix in ('.ttml', '.dfxp'):
        return read_ttml(text)
    if suffix == '.scc':
        return read_scc(text)
    raise ValueError('Unsupported subtitle format: ' + suffix)

def save(path, cues):
    path = Path(path)
    suffix = path.suffix.lower()
    cues = checked(cues)
    if suffix in ('.xf', '.mid', '.midi', '.kar'):
        from xf_lyrics import write_midi
        write_midi(path, cues)
        return
    if suffix in ('.srt', '.vtt'):
        blocks = []
        for i, cue in enumerate(cues, 1):
            if round(cue.start * 1000) >= round(cue.end * 1000):
                raise ValueError('SRT/VTT cue is shorter than millisecond time resolution')
            text = html.escape(cue.text, quote=False)
            if suffix == '.vtt' and cue.spans:
                cursor, parts, previous = (0, [], cue.start)
                for a, b, l, r in cue.spans:
                    if l < cursor or cue.start + a < previous - 1e-09:
                        raise ValueError('WebVTT export needs ordered, nonoverlapping text spans')
                    parts.append(html.escape(cue.text[cursor:l], quote=False))
                    if previous < cue.start + a < cue.end:
                        parts.append('<' + clock(cue.start + a) + '>')
                    parts.append(html.escape(cue.text[l:r], quote=False))
                    if cue.start + a < cue.start + b < cue.end:
                        parts.append('<' + clock(cue.start + b) + '>')
                    cursor, previous = (r, cue.start + b)
                parts.append(html.escape(cue.text[cursor:], quote=False))
                text = ''.join(parts)
            blocks.append(f"{i}\n{clock(cue.start, ',' if suffix == '.srt' else '.')} --> {clock(cue.end, ',' if suffix == '.srt' else '.')}\n{text}")
        output = ('WEBVTT\n\n' if suffix == '.vtt' else '') + '\n\n'.join(blocks) + '\n'
    elif suffix in ('.ttml', '.dfxp'):
        ET.register_namespace('', TT)
        root = ET.Element('{' + TT + '}tt', {'{' + XML + '}lang': 'und', '{' + XML + '}space': 'preserve'})
        div = ET.SubElement(ET.SubElement(root, '{' + TT + '}body'), '{' + TT + '}div')
        for cue in cues:
            p = ET.SubElement(div, '{' + TT + '}p', begin=f'{cue.start:.6f}s', end=f'{cue.end:.6f}s')
            cursor, last = (0, None)

            def add(value):
                nonlocal last
                parts = value.split('\n')
                if last is None:
                    p.text = (p.text or '') + parts[0]
                else:
                    last.tail = (last.tail or '') + parts[0]
                for piece in parts[1:]:
                    last = ET.SubElement(p, '{' + TT + '}br')
                    last.tail = piece
            for a, b, l, r in cue.spans:
                if l < cursor:
                    raise ValueError('TTML export needs ordered nonoverlapping text spans')
                add(cue.text[cursor:l])
                last = ET.SubElement(p, '{' + TT + '}span', begin=f'{a:.6f}s', end=f'{b:.6f}s')
                pieces = cue.text[l:r].split('\n')
                last.text = pieces[0]
                for piece in pieces[1:]:
                    ET.SubElement(last, '{' + TT + '}br').tail = piece
                cursor = r
            add(cue.text[cursor:])
        output = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode') + '\n'
    elif suffix in ('.ass', '.ssa'):
        v4 = suffix == '.ssa'
        output = '[Script Info]\nScriptType: ' + ('v4.00' if v4 else 'v4.00+') + '\nPlayResX: 1280\nPlayResY: 720\n' + ('[V4 Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding\nStyle: Default,Arial,54,16777215,65535,0,0,0,0,1,2,0,2,30,30,50,0,1\n' if v4 else '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,54,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,50,1\n') + '[Events]\nFormat: ' + ('Marked' if v4 else 'Layer') + ', Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'

        def at(t):
            cs = round(t * 100)
            return f'{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}'

        def escape(s):
            return s.replace('\\', '\\\\').replace('{', '｛').replace('}', '｝').replace('\n', '\\N')
        for cue in cues:
            if round(cue.start * 100) >= round(cue.end * 100):
                raise ValueError('ASS/SSA cue is shorter than centisecond time resolution; use TTML or JSON')
            body, cursor = ('', 0)
            for a, b, l, r in cue.spans:
                if l < cursor:
                    raise ValueError('ASS/SSA export needs ordered nonoverlapping text spans')
                gap = escape(cue.text[cursor:l])
                body += '{\\r}' + gap if gap else ''
                body += ('{\\k' + str(round((b - a) * 100)) + '}' if v4 else '{\\kt' + str(round(a * 100)) + '\\kf' + str(round((b - a) * 100)) + '}') + escape(cue.text[l:r])
                cursor = r
            tail = escape(cue.text[cursor:])
            body += '{\\r}' + tail if tail and cue.spans else tail
            output += f"Dialogue: {('Marked=0' if v4 else '0')},{at(cue.start)},{at(cue.end)},Default,,0,0,0,,{body}\n"
    elif suffix == '.scc':
        from pycaption import Caption, CaptionNode
        from scc_lyrics import write
        from pycaption.scc.constants import CHARACTER_TO_CODE, SPECIAL_OR_EXTENDED_CHAR_TO_CODE
        supported = set(CHARACTER_TO_CODE) | set(SPECIAL_OR_EXTENDED_CHAR_TO_CODE) | {'\n'}
        captions = []
        for i, cue in enumerate(cues):
            missing = set(cue.text) - supported
            if missing:
                raise ValueError('SCC/CEA-608 cannot encode these characters: ' + ''.join(sorted(missing)) + '; use TTML, ASS, SRT or VTT')
            if i and cue.start < cues[i - 1].end:
                raise ValueError('SCC single-channel export cannot preserve overlapping cues; use TTML or ASS')
            lines = cue.text.split('\n')
            if sum((max(1, len(textwrap.wrap(line, 32))) for line in lines)) > 15:
                raise ValueError('SCC caption exceeds the 15-row display; split it into shorter cues')
            nodes = []
            for j, line in enumerate(lines):
                if j:
                    nodes.append(CaptionNode.create_break())
                nodes.append(CaptionNode.create_text(line))
            captions.append(Caption(round(cue.start * 1000000.0), round(cue.end * 1000000.0), nodes))
        output = write(captions)
    else:
        raise ValueError('Unsupported subtitle format: ' + suffix)
    path.write_text(output, encoding='utf-8')
