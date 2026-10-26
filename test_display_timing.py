"""Display lead/hold/opacity and deterministic vacant-slot scheduling."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
import bootstrap
import av
import numpy as np
from lyrics import Cue
from lyric_layout import build_display_rows
from media import Renderer, Style, default_font, export_video
from presentation import Presentation
from engine import Settings
from timing_style import TimingStyleDialog

def row(begin, finish, text='田'):
    cue = Cue(begin - 2, finish + 3, text, [(2, finish - begin + 2, 0, len(text))], begin)
    return (cue, text, list(range(len(text))))

class DisplayTimingTests(unittest.TestCase):

    def test_lead_hold_and_eased_opacity(self):
        style = Style(timing_enabled=True, fill_early=False)
        entry = build_display_rows([row(5, 6)], 2, style, Renderer.row_complete)[0]
        self.assertEqual((entry.show, entry.fade_start), (1, 8))
        self.assertAlmostEqual(entry.end, 8.2)
        self.assertEqual(entry.opacity(1), 0)
        self.assertAlmostEqual(entry.opacity(1.1), 0.5)
        self.assertEqual(entry.opacity(2), 1)
        self.assertAlmostEqual(entry.opacity(8.1), 0.5)
        self.assertEqual(entry.opacity(8.2), 0)

    def test_early_fill_bound_and_no_slot_overlap(self):
        rows = [row(5, 6), row(10, 11), row(15, 16)]
        style = Style(timing_enabled=True, fill_early=True)
        plan = build_display_rows(rows, 2, style, Renderer.row_complete)
        self.assertEqual([e.slot for e in plan], [0, 1, 0])
        self.assertEqual(plan[2].show, 9)
        self.assertGreaterEqual(plan[2].show, plan[0].end)
        style.fill_early = False
        style.immediate_line_change = True
        plan = build_display_rows(rows, 2, style, Renderer.row_complete)
        self.assertEqual(plan[2].show, 11)

    def test_whole_page_waits_for_all_rows_and_zero_fades(self):
        style = Style(timing_enabled=True, fill_early=False, hold_ms=0, fade_in_ms=0, fade_out_ms=0)
        plan = build_display_rows([row(5, 6), row(7, 9), row(10, 11)], 2, style, Renderer.row_complete)
        self.assertGreaterEqual(plan[2].show, 9)
        self.assertEqual(plan[0].opacity(1), 1)
        self.assertEqual(plan[0].opacity(6), 0)

    def test_alpha_fade_only_affects_lyrics_and_seeks_are_stateless(self):
        style = Style(font=default_font(), size=48, bottom=30, timing_enabled=True, fill_early=False)
        cues = [row(5, 6)[0]]
        renderer = Renderer()
        half = np.asarray(renderer.render((320, 180), None, cues, 1.1, style, transparent=True))
        full = np.asarray(renderer.render((320, 180), None, cues, 2, style, transparent=True))
        self.assertEqual(int(half[:, :, 3].max()), 128)
        self.assertEqual(int(full[:, :, 3].max()), 255)
        visible = half[:, :, 3] > 0
        np.testing.assert_array_equal(half[visible, :3], full[visible, :3])
        renderer.render((320, 180), None, cues, 8.1, style, transparent=True)
        np.testing.assert_array_equal(half, np.asarray(renderer.render((320, 180), None, cues, 1.1, style, transparent=True)))
        rgb = renderer.render((320, 180), None, cues, 1.1, style)
        self.assertEqual(rgb.getpixel((0, 0)), (0, 255, 0))

    def test_mov_preserves_partial_opacity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fade.mov'
            style = Style(font=default_font(), size=48, timing_enabled=True, fill_early=False, advance_ms=0, hold_ms=0, fade_in_ms=200, fade_out_ms=200)
            export_video(path, cues=[row(0, 0.2)[0]], style=style, duration=0.4, size=(320, 180), fps=30, output_format='prores4444')
            with av.open(str(path)) as stream:
                frames = list(stream.decode(video=0))
                self.assertLessEqual(abs(int(frames[3].to_ndarray(format='rgba')[:, :, 3].max()) - 128), 2)
                self.assertLessEqual(abs(int(frames[9].to_ndarray(format='rgba')[:, :, 3].max()) - 128), 2)

    def test_dialog_defaults_validation_and_trace_cleanup(self):
        root = tk.Tk()
        root.withdraw()
        owner = Presentation(SimpleNamespace(root=root, ready=False, song=None, play=lambda: None, engine=SimpleNamespace(position=lambda: 0, settings=Settings(), song=None, variant=None)))
        try:
            owner.open()
            owner.window.withdraw()
            dialog = TimingStyleDialog(owner)
            dialog.window.withdraw()
            root.update()
            dialog.defaults()
            root.update()
            dialog.apply()
            self.assertTrue(owner.style.timing_enabled)
            self.assertEqual(owner.style.advance_ms, 4000)
            dialog.window.destroy()
            root.update()
            for value in owner.timing_vars.values():
                self.assertFalse(value.trace_info())
            owner.timing_vars['max_advance_ms'].set('1')
            with patch('presentation.messagebox.showerror') as error:
                self.assertFalse(owner.apply())
                error.assert_called_once()
        finally:
            owner.close()
            root.destroy()
if __name__ == '__main__':
    unittest.main()
