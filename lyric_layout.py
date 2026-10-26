"""Deterministic display-only lyric scheduling; never modifies source timing."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class DisplayRow:
    row: tuple
    slot: int
    show: float
    fade_start: float
    end: float
    fade_in: float
    fade_out: float

    def opacity(self, position):
        if not self.show <= position < self.end:
            return 0.0
        incoming = min(1.0, max(0.0, (position-self.show)/self.fade_in)) if self.fade_in else 1.0
        outgoing = min(1.0, max(0.0, (self.end-position)/self.fade_out)) if self.fade_out else 1.0
        # Smoothstep eases the visibility; character color sweeps remain linear.
        return min(incoming*incoming*(3-2*incoming), outgoing*outgoing*(3-2*outgoing))


def row_interval(row, complete):
    cue, _, indices = row
    starts = []
    for index in indices:
        if cue.text[index].isspace():
            continue
        span = next((s for s in cue.spans if s[2] <= index < s[3]), None)
        if span:
            a,b,left,right = span
            starts.append(cue.start+a+(b-a)*(index-left)/(right-left))
    begin = min(starts) if starts else (cue.sing_start if cue.sing_start is not None else cue.start)
    finish = complete(cue, indices) if cue.spans else cue.end
    return begin, max(begin, finish)


def build_display_rows(rows, capacity, style, complete):
    lead, hold = style.advance_ms/1000, style.hold_ms/1000
    incoming, outgoing = style.fade_in_ms/1000, style.fade_out_ms/1000
    maximum = max(lead, style.max_advance_ms/1000)
    result = []

    def make(row, slot, show, finish):
        fade_start = max(show, finish)+hold
        return DisplayRow(row, slot, show, fade_start, fade_start+outgoing, incoming, outgoing)

    if style.fill_early or style.immediate_line_change:
        free = [-math.inf]*capacity
        for row in rows:
            begin, finish = row_interval(row, complete)
            slot = min(range(capacity), key=lambda i: (free[i],i))
            show = max(free[slot], begin-(maximum if style.fill_early else lead))
            entry = make(row, slot, show, finish)
            free[slot] = entry.end
            result.append(entry)
    else:
        available = -math.inf
        for offset in range(0,len(rows),capacity):
            group = rows[offset:offset+capacity]
            intervals = [row_interval(row,complete) for row in group]
            start = max(available,min(begin-lead for begin,_ in intervals))
            entries = [make(row,slot,max(start,begin-lead),finish)
                       for slot,(row,(begin,finish)) in enumerate(zip(group,intervals))]
            result.extend(entries)
            available = max(e.end for e in entries)
    return result
