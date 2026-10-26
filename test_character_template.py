"""MI3 default character templates follow speed shape, retain provenance and roundtrip."""
from pathlib import Path
import tempfile
import unittest
import bootstrap
import lyrics
ROOT = Path(__file__).resolve().parent.parent

class CharacterTemplateTests(unittest.TestCase):

    def test_speed_curve_and_stop(self):
        data = {'lines': [{'display_seconds': 0, 'sing_seconds': 0, 'clear_seconds': 2, 'mode': 0, 'text': '甲乙'}], 'color_changes': [{'time_cs': 0, 'command': 0, 'speed_raw': 10000, 'multiplier': 1}, {'time_cs': 100, 'command': 0, 'speed_raw': 30000, 'multiplier': 1}]}
        cue = lyrics.character_template(data)[0]
        self.assertAlmostEqual(cue.spans[0][1], 1.34, places=5)
        self.assertEqual(cue.spans[-1][1], 2)
        self.assertEqual(cue.timing_source, 'estimated-speed-font-v2-cs')
        data['color_changes'][1]['speed_raw'] = 0
        data['lines'][0]['clear_seconds'] = 5
        self.assertEqual(lyrics.character_template(data)[0].spans[-1][1], 1)

    def test_real_samples_and_template_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('CE000001', 'CE010000', 'CE053877'):
                for resource in (0, 1):
                    cues = lyrics.mi3_cues(ROOT / (name + '.MI3'), resource)
                    for cue in cues:
                        self.assertEqual(len(cue.spans), len(cue.text.replace('\n', '')))
                        self.assertTrue(cue.timing_source.startswith('estimated'))
                        for a, b, left, right in cue.spans:
                            self.assertLessEqual(a, b)
                            self.assertGreaterEqual(a + cue.start + 1e-06, cue.sing_start)
                            self.assertLessEqual(b + cue.start, cue.end + 1e-06)
                            self.assertEqual(right, left + 1)
                    for extension in ('.json', '.csv'):
                        path = Path(directory) / ('roundtrip' + extension)
                        lyrics.save_cues(path, cues)
                        loaded = lyrics.load(path)
                        self.assertEqual(loaded[0].timing_source, cues[0].timing_source)
                        self.assertEqual([tuple(s) for s in loaded[0].spans], cues[0].spans)
            outputs = lyrics.export_template(ROOT / 'CE053877.MI3', Path(directory) / 'template', filter_numeric=True)
            for path in outputs[:2]:
                cues = lyrics.load(path)
                self.assertTrue(cues[0].spans)
                self.assertTrue(cues[0].timing_source.startswith('estimated'))
                self.assertFalse(any((lyrics.NUMERIC_MARKER.search(c.text) for c in cues)))
if __name__ == '__main__':
    unittest.main()
