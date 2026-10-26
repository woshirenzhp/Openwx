"""CEA-608 text coding via pycaption, exact NTSC frame scheduling in this adapter."""
import re
FPS = 30000 / 1001

def frame_number(stamp):
    h, m, s, f = map(int, re.split('[:;]', stamp))
    if m >= 60 or s >= 60 or f >= 30:
        raise ValueError('Invalid SCC timecode: ' + stamp)
    minutes = h * 60 + m
    if ';' in stamp and m % 10 and (s == 0) and (f < 2):
        raise ValueError('Invalid SCC drop-frame label: ' + stamp)
    return (h * 3600 + m * 60 + s) * 30 + f - (2 * (minutes - minutes // 10) if ';' in stamp else 0)

def timecode(frame):
    d, m = divmod(frame, 17982)
    nominal = frame + 18 * d + 2 * max(0, (m - 2) // 1798)
    h, rest = divmod(nominal, 108000)
    minute, rest = divmod(rest, 1800)
    second, f = divmod(rest, 30)
    if h >= 24:
        raise ValueError('SCC timecodes must be shorter than 24 hours')
    return f'{h:02d}:{minute:02d}:{second:02d};{f:02d}'

def read(text):
    from lyrics import Cue
    from pycaption import SCCReader
    from pycaption.scc.reader import _SccTimeTranslator

    class FrameClock(_SccTimeTranslator):

        def get_time(self):
            return max(0, round((frame_number(self._time) + self._frames) / FPS * 1000000.0 - self.offset))
    reader = SCCReader()
    reader.time_translator = FrameClock()
    captions = reader.read(text)
    return [Cue(c.start / 1000000.0, c.end / 1000000.0, c.get_text(), timing_source='scc-cea608') for c in captions.get_captions(captions.get_languages()[0])]

def write(captions):
    from pycaption import SCCWriter
    writer = SCCWriter()
    frames = {}
    last_swap = -2
    for i, cap in enumerate(captions):
        begin, end = (round(cap.start / 1000000.0 * FPS), round(cap.end / 1000000.0 * FPS))
        payload = ['94ae', '94ae', '9420', '9420'] + writer._text_to_code(cap).split()
        earliest = last_swap + 2
        if i == 0:
            begin = max(begin, len(payload))
        available = []
        candidate = begin - 1
        while candidate >= earliest and len(available) < len(payload):
            if candidate not in frames:
                available.append(candidate)
            candidate -= 1
        available.reverse()
        if len(available) < len(payload) or end <= begin + 1:
            raise ValueError('SCC cues are too dense or short for CEA-608 transmission; use SRT/TTML')
        for f, word in zip(available[-len(payload):], payload):
            frames[f] = word
        if begin in frames or begin + 1 in frames:
            raise ValueError('SCC caption swap conflicts with a previous clear command')
        frames[begin] = frames[begin + 1] = '942f'
        last_swap = begin
        next_start = round(captions[i + 1].start / 1000000.0 * FPS) if i + 1 < len(captions) else None
        if next_start is None or next_start > end:
            frames[end] = '942c'
            if next_start is None or next_start > end + 1:
                frames[end + 1] = '942c'
    lines, run, first, previous = ([], [], None, None)
    for frame in sorted(frames):
        if previous is None or frame != previous + 1:
            if run:
                lines.append(timecode(first) + '\t' + ' '.join(run))
            first, run = (frame, [])
        run.append(frames[frame])
        previous = frame
    if run:
        lines.append(timecode(first) + '\t' + ' '.join(run))
    return 'Scenarist_SCC V1.0\n\n' + '\n\n'.join(lines) + '\n'
