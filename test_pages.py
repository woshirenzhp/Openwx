"""Page changes wait for every visible row, including wrapped character spans."""
import unittest
import bootstrap
from lyrics import Cue
from media import Renderer, Style, default_font
from PIL import ImageFont

class PageTests(unittest.TestCase):

    def setUp(self):
        self.renderer = Renderer()
        self.style = Style(font=default_font(), size=40, bottom=20, page_lines=2)
        self.font = ImageFont.truetype(self.style.font, self.style.size)

    def rows(self, cues, at, width=640):
        return self.renderer.page_at(cues, at, self.font, (self.style.font, self.style.size), width, 360, self.style)

    def test_all_rows_finish_before_atomic_change_and_seek_back(self):
        cues = [Cue(0, 1.5, '甲', [(0, 1, 0, 1)]), Cue(0.3, 4, '乙', [(1, 2.7, 0, 1)]), Cue(2, 6, '丙', [(1, 2, 0, 1)]), Cue(2.5, 7, '丁', [(2, 3, 0, 1)])]
        self.assertEqual([r[1] for r in self.rows(cues, 0)], ['甲', '乙'])
        self.assertEqual([r[1] for r in self.rows(cues, 2.9)], ['甲', '乙'])
        self.assertEqual([r[1] for r in self.rows(cues, 3)], ['丙', '丁'])
        self.assertEqual([r[1] for r in self.rows(cues, 1)], ['甲', '乙'])
        self.assertEqual(self.rows(cues, 7), [])

    def test_wrapped_rows_and_future_page_keep_character_indices(self):
        cue = Cue(0, 8, '甲乙\n丙丁\n戊己', [(0, 6, 0, 8)])
        first = self.rows([cue], 1)
        self.assertEqual([r[1] for r in first], ['甲乙', '丙丁'])
        self.assertEqual(first[1][2], [3, 4])
        self.assertEqual([r[1] for r in self.rows([cue], 3.8)], ['戊己'])
        self.style.page_lines = 1
        self.assertEqual([r[1] for r in self.rows([cue], 1.6)], ['丙丁'])

    def test_hold_until_next_page_due_and_line_only_fallback(self):
        cues = [Cue(0, 2, '甲', sing_start=1), Cue(0, 3, '乙', sing_start=2), Cue(10, 12, '丙', sing_start=11)]
        self.assertEqual([r[1] for r in self.rows(cues, 9)], ['甲', '乙'])
        self.assertEqual([r[1] for r in self.rows(cues, 10)], ['丙'])
        self.assertEqual(self.rows(cues, -1), [])

    def test_immediate_switch_rolls_one_line_and_toggle_restores_page(self):
        cues = [Cue(0, 5, '甲', [(0, 1, 0, 1)]), Cue(0.2, 5, '乙', [(1, 2, 0, 1)]), Cue(0.4, 5, '丙', [(2, 3, 0, 1)])]
        self.assertEqual([r[1] for r in self.rows(cues, 1.1)], ['甲', '乙'])
        self.style.immediate_line_change = True
        self.assertEqual([r[1] for r in self.rows(cues, 0.9)], ['甲', '乙'])
        self.assertEqual([r[1] for r in self.rows(cues, 1)], ['乙', '丙'])
        self.assertEqual([r[1] for r in self.rows(cues, 2.1)], ['乙', '丙'])
        self.assertEqual([r[1] for r in self.rows(cues, 2.2)], ['丙'])
        self.assertEqual(self.rows(cues, 3.4), [])
        self.style.immediate_line_change = False
        self.assertEqual([r[1] for r in self.rows(cues, 1.1)], ['甲', '乙'])

    def test_immediate_without_character_timing_waits_until_end(self):
        self.style.immediate_line_change = True
        cues = [Cue(0, 3, '甲', sing_start=0.5), Cue(0, 5, '乙', sing_start=1), Cue(0, 6, '丙', sing_start=2)]
        self.assertEqual([r[1] for r in self.rows(cues, 2.9)], ['甲', '乙'])
        self.assertEqual([r[1] for r in self.rows(cues, 3)], ['乙', '丙'])
if __name__ == '__main__':
    unittest.main()
