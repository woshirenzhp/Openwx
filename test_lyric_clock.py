"""Compare clock reconstruction with firmware verification and independent tick sums."""
from pathlib import Path
import json
import unittest
import bootstrap
import lyrics
from lyric_clock import SweepClock
ROOT = Path(__file__).resolve().parent.parent

def event(at, speed, lane=0, multiplier=1):
    return dict(time_cs=at, speed_raw=speed, command=lane, multiplier=multiplier)

class LyricClockTests(unittest.TestCase):

    def test_original_mips_arithmetic_cases(self):
        report = json.loads((ROOT / 'lyric_analysis/telop_firmware_verification.json').read_text('utf8'))
        self.assertTrue(report['all_passed'])
        for case in report['pixel_delta_cases']:
            rate = case['rate']
            clock = SweepClock([event(0, rate, multiplier=100)], case['previous_cs'], case['now_cs'], 0)
            self.assertEqual(clock.distance, case['pixels'])

    def test_pause_boundary_belongs_to_next_motion(self):
        data = dict(lines=[dict(display_seconds=0, sing_seconds=0, clear_seconds=3, mode=0, text='甲乙')], color_changes=[event(0, 10000), event(100, 0), event(200, 10000)])
        cue = lyrics.character_template(data)[0]
        self.assertEqual(cue.spans[0][:2], (0, 1))
        self.assertEqual(cue.spans[1][:2], (2, 3))
        self.assertEqual(cue.timing_source, 'estimated-speed-font-v2-cs')

    def test_initial_silence_lane_isolation_and_equal_time_order(self):
        clock = SweepClock([event(0, 30000, 1), event(20, 10000), event(20, 20000), event(60, 0)], 0, 100, 0)
        self.assertEqual(clock.at(20), 0)
        self.assertEqual(clock.at(21), 2)
        self.assertEqual(clock.distance, 80)
        self.assertEqual(clock.last_before_motion(0), 20)
        self.assertEqual(clock.first_reached(80), 60)
        self.assertEqual(SweepClock([event(0, 10000, 2)], 0, 100, 2).distance, 0)

    def test_native_cs_authoritative_and_quantized_boundaries(self):
        data = dict(lines=[dict(display_cs=200, sing_cs=250, clear_cs=450, display_seconds=999, sing_seconds=999, clear_seconds=999, mode=0, text='甲乙')], color_changes=[event(250, 10000), event(350, 30000)])
        cue = lyrics.character_template(data)[0]
        self.assertEqual((cue.start, cue.sing_start, cue.end), (2, 2.5, 4.5))
        for a, b, _, _ in cue.spans:
            self.assertAlmostEqual(a * 100, round(a * 100))
            self.assertAlmostEqual(b * 100, round(b * 100))

    def test_all_sample_clocks_match_independent_tick_sum(self):
        for name in ('CE000001', 'CE010000', 'CE053877'):
            for resource in (0, 1):
                data = lyrics.mi3_timing(ROOT / (name + '.MI3'), resource)
                events = data['color_changes']
                for i, row in enumerate(data['lines']):
                    begin = row['sing_cs']
                    end = min([row['clear_cs']] + [r['sing_cs'] for r in data['lines'][i + 1:] if r['mode'] == row['mode'] and r['sing_cs'] > begin])
                    clock = SweepClock(events, begin, end, row['mode'])
                    selected = [e for e in events if e['command'] == row['mode']]
                    at_event = 0
                    rate = 0
                    distance = 0
                    for tick in range(begin, end):
                        while at_event < len(selected) and selected[at_event]['time_cs'] <= tick:
                            e = selected[at_event]
                            rate = e['speed_raw'] * e['multiplier'] // 100
                            at_event += 1
                        distance += rate * (tick + 1) // 100 - rate * tick // 100
                        self.assertEqual(clock.at(tick + 1), distance)
                    self.assertEqual(clock.distance, distance)
if __name__ == '__main__':
    unittest.main()
