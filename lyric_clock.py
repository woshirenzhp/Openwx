"""Firmware-derived SNG sweep clock shared by Chinese and English editions.

SNG timestamps are integer centiseconds. set_cc_speed uses raw*multiplier//100;
the worker subtracts floor(rate*t/100) at absolute clocks, not a rounded delta.
This reconstructs event-boundary arithmetic, not the device's thread scheduling.
"""
from bisect import bisect_right
from dataclasses import dataclass
import math


def centiseconds(row, name):
    value = row.get(name + '_cs')
    if value is None:
        value = round(float(row[name + '_seconds']) * 100)
    if not math.isfinite(value) or value < 0 or int(value) != value:
        raise ValueError('Invalid centisecond timestamp')
    return int(value)


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    rate: int
    distance: int


class SweepClock:
    def __init__(self, events, begin_cs, end_cs, lane):
        self.begin, self.end = begin_cs, end_cs
        self.segments = []
        self.distance = 0
        if not 0 <= begin_cs <= end_cs:
            raise ValueError('Invalid sweep clock range')
        rate, at = 0, begin_cs

        def append(until):
            nonlocal at
            if until > at:
                if rate * until > 0xFFFFFFFF:
                    raise ValueError('Sweep arithmetic exceeds the verified 32-bit range')
                self.segments.append(Segment(at, until, rate, self.distance))
                self.distance += rate * until // 100 - rate * at // 100
                at = until

        # Only firmware commands 0 and 1 update a sweep lane. Equal-time events
        # retain file order; the last matching event determines the next rate.
        selected = sorted((e for e in events if lane in (0, 1) and e['command'] == lane),
                          key=lambda e: e['time_cs'])
        for event in selected:
            clock = event['time_cs']
            raw, multiplier = event['speed_raw'], event['multiplier']
            if any(not isinstance(v, int) for v in (clock, raw, multiplier)) or not (
                    0 <= clock <= 0xFFFFFFFF and 0 <= raw <= 65535 and 0 <= multiplier <= 255):
                raise ValueError('Invalid SNG color-change record')
            if clock <= begin_cs:
                rate = raw * multiplier // 100
            elif clock < end_cs:
                append(clock)
                rate = raw * multiplier // 100
            else:
                break
        append(end_cs)
        self.starts = [s.start for s in self.segments]

    def at(self, clock):
        if clock <= self.begin or not self.segments:
            return 0
        if clock >= self.end:
            return self.distance
        s = self.segments[bisect_right(self.starts, clock) - 1]
        return s.distance + s.rate * clock // 100 - s.rate * s.start // 100

    def first_reached(self, target):
        """First centisecond at or above a cumulative distance (character end)."""
        low, high = self.begin, self.end
        while low < high:
            mid = (low + high) // 2
            if self.at(mid) >= target - 1e-9:
                high = mid
            else:
                low = mid + 1
        return low

    def last_before_motion(self, target):
        """End of the plateau at a boundary, rather than its beginning."""
        low, high = self.begin, self.end
        while low < high:
            mid = (low + high + 1) // 2
            if self.at(mid) <= target + 1e-9:
                low = mid
            else:
                high = mid - 1
        return low
