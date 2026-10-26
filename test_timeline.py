"""Regression checks for reversible numeric-marker filtering and character timing."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
import bootstrap
import lyrics
from timeline import TimelineModel, TimelineEditor, seconds
from presentation import Presentation
from engine import Settings

class TimelineTests(unittest.TestCase):

    def test_exact_numeric_markers_and_span_remapping(self):
        text = '甲[0125]乙[9999]丙[123][12345][AB12][１２３４]'
        source = lyrics.Cue(1, 10, text, [(0, 1, 0, 1), (1, 2, 1, 7), (2, 3, 7, 8)])
        self.assertEqual(lyrics.output_cues([source])[0].text, text)
        filtered = lyrics.output_cues([source], True)[0]
        self.assertEqual(filtered.text, '甲乙丙[123][12345][AB12][１２３４]')
        self.assertEqual(filtered.spans, [(0, 1, 0, 1), (2, 3, 1, 2)])
        self.assertEqual(source.text, text)
        self.assertEqual(len(source.spans), 3)
        self.assertEqual(lyrics.clean_text('[0000][9999]'), '')

    def test_roundtrip_character_times_and_optional_export_filter(self):
        cue = lyrics.Cue(1, 9, '甲[0125]乙', [(0.123, 0.456, 0, 1), (2.789, 3.123, 7, 8)], 1.1)
        with tempfile.TemporaryDirectory() as folder:
            for suffix in ('.json', '.csv'):
                path = Path(folder) / ('raw' + suffix)
                lyrics.save_cues(path, [cue])
                back = lyrics.load(path)[0]
                self.assertEqual(back.text, cue.text)
                self.assertEqual([tuple(s) for s in back.spans], cue.spans)
                lyrics.save_cues(path, [cue], True)
                back = lyrics.load(path)[0]
                self.assertEqual(back.text, '甲乙')
                self.assertEqual([tuple(s) for s in back.spans], [(0.123, 0.456, 0, 1), (2.789, 3.123, 1, 2)])

    def test_model_millisecond_edit_undo_and_templates(self):
        model = TimelineModel([lyrics.Cue(1, 7, '甲乙', sing_start=2)])
        self.assertIsNone(model.char_time(0, 0))
        model.set_char(0, 0, 2.123, 3.456)
        self.assertEqual(model.char_time(0, 0), (2.123, 3.456))
        model.undo()
        self.assertIsNone(model.char_time(0, 0))
        model.redo()
        model.shift([0], 0.1)
        self.assertAlmostEqual(model.char_time(0, 0)[0], 2.223)
        model.distribute(0)
        self.assertEqual(len(model.cues[0].spans), 2)
        self.assertEqual(seconds('01:02.123'), 62.123)
        with self.assertRaises(ValueError):
            model.set_char(0, 0, 0, 1)

    def test_gui_preserves_raw_edits_and_filter_toggle(self):
        root = tk.Tk()
        root.withdraw()
        engine = SimpleNamespace(position=lambda: 2.123, settings=Settings(), song=None, variant=None, command=lambda *args: None)
        owner = Presentation(SimpleNamespace(root=root, ready=True, song=None, engine=engine, play=lambda: None))
        editor = None
        try:
            owner.open()
            owner.window.withdraw()
            owner.set_cues([lyrics.Cue(0, 10, '甲[0125]乙', sing_start=1)], 'test')
            self.assertFalse(owner.filter_numeric.get())
            editor = TimelineEditor(owner)
            editor.window.withdraw()
            root.update()
            editor.model.set_char(0, 7, 2.123, 3.456)
            editor.apply_preview()
            self.assertEqual(owner.cues[0].text, '甲[0125]乙')
            revision = owner.cues_revision
            owner.filter_numeric.set(True)
            owner.filter_changed()
            self.assertEqual(owner.output_cues()[0].text, '甲乙')
            self.assertEqual(owner.output_cues()[0].spans[0][2:], (1, 2))
            self.assertEqual(owner.cues_revision, revision)
            with tempfile.TemporaryDirectory() as folder:
                path = str(Path(folder) / 'chars.json')
                with patch('timeline.filedialog.asksaveasfilename', return_value=path):
                    editor.save()
                self.assertEqual(lyrics.load(path)[0].text, '甲乙')
            owner.filter_numeric.set(False)
            owner.filter_changed()
            self.assertEqual(owner.output_cues()[0].text, '甲[0125]乙')
            owner.set_cues([lyrics.Cue(0, 4, '新歌曲')], 'new')
            editor.apply_preview()
            self.assertEqual(owner.cues[0].text, '新歌曲')
        finally:
            if editor:
                editor.close()
            owner.close()
            root.destroy()
if __name__ == '__main__':
    unittest.main()
