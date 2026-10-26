"""Live preview lyric editing, reversible text changes and precise character nudges."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import tkinter as tk
import unittest
from lyrics import Cue, load, save_cues
from timeline import TimelineModel
from presentation import Presentation, Preview
from engine import Settings

class LiveEditorTests(unittest.TestCase):

    def make_owner(self):
        root = tk.Tk()
        root.withdraw()
        engine = SimpleNamespace(settings=Settings(), song=None, variant=None, position=lambda: 1.5)
        owner = Presentation(SimpleNamespace(root=root, ready=False, song=None, engine=engine, play=lambda: None))
        owner.resolution.set('640x360')
        owner.local_position = 1.5
        owner.set_cues([Cue(0, 4, 'AB', [(0.5, 1, 0, 1), (1.2, 2, 1, 2)], 0.5)], 'test')
        return (root, owner)

    def pump(self, root, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        self.assertTrue(predicate())

    def close_owner(self, root, owner):
        owner.close()
        root.update_idletasks()
        for job in root.tk.call('after', 'info'):
            root.after_cancel(job)
        root.destroy()

    def test_insert_delete_text_remaps_unchanged_character_times(self):
        model = TimelineModel([Cue(1, 6, 'ABC', [(0, 1, 0, 1), (1, 2, 1, 2), (2, 3, 2, 3)], 1)])
        model.update_line(0, 1, 1, 6, 'AXBC')
        self.assertEqual(model.char_time(0, 0), (1, 2))
        self.assertIsNone(model.char_time(0, 1))
        self.assertEqual(model.char_time(0, 2), (2, 3))
        self.assertEqual(model.char_time(0, 3), (3, 4))
        model.update_line(0, 1, 1, 6, 'AC')
        self.assertEqual(model.char_time(0, 1), (3, 4))
        model.undo()
        self.assertEqual(model.cues[0].text, 'AXBC')
        model.redo()
        self.assertEqual(model.cues[0].text, 'AC')

    def test_partial_syllable_edit_does_not_invent_character_times(self):
        model = TimelineModel([Cue(0, 5, 'Hello world', [(0, 2, 0, 5), (2, 4, 6, 11)])])
        model.update_line(0, 0, 0, 5, 'Hallo world')
        self.assertEqual(model.cues[0].spans, [(2, 4, 6, 11)])
        self.assertIsNone(model.char_time(0, 1))

    def test_multi_character_nudges_are_atomic_millisecond_and_reversible(self):
        model = TimelineModel([Cue(0, 4, 'AB', [(1, 2, 0, 1), (2, 3, 1, 2)])])
        model.nudge_chars(0, {0, 1}, 0.001, 'move')
        self.assertEqual(model.char_time(0, 0), (1.001, 2.001))
        self.assertEqual(model.char_time(0, 1), (2.001, 3.001))
        before = list(model.cues[0].spans)
        with self.assertRaises(ValueError):
            model.nudge_chars(0, {0, 1}, 1.5, 'end')
        self.assertEqual(model.cues[0].spans, before)
        model.undo()
        self.assertEqual(model.char_time(0, 0), (1, 2))

    def test_shortened_line_cannot_leave_character_times_outside_its_bounds(self):
        model = TimelineModel([Cue(0, 4, 'AB', [(1, 2, 0, 1), (2, 3, 1, 2)])])
        with self.assertRaises(ValueError):
            model.update_line(0, 0, 0, 2.5, 'AB')
        self.assertEqual(model.cues[0].end, 4)
        self.assertEqual(len(model.past), 0)

    def test_preview_opens_shared_live_editor_and_typing_updates_without_resetting_cursor(self):
        root, owner = self.make_owner()
        preview = None
        try:
            preview = Preview(owner, False)
            preview.window.withdraw()
            editor = preview.open_editor()
            editor.window.withdraw()
            self.assertTrue(editor.auto.get())
            self.assertTrue(editor.auto_text.get())
            self.assertIs(owner.open_timeline(live=True), editor)
            editor.window.withdraw()
            revision = owner.cues_revision
            editor.text.mark_set('insert', '1.1')
            editor.text.insert('insert', 'X')
            self.pump(root, lambda: owner.cues[0].text == 'AXB')
            self.assertGreater(owner.cues_revision, revision)
            self.assertEqual(editor.text.index('insert'), '1.2')
            self.assertEqual(owner.cues[0].spans, [(0.5, 1, 0, 1), (1.2, 2, 2, 3)])
            self.assertEqual(editor.char_tree.get_children(), ('0', '1', '2'))
            editor.char_tree.selection_set('2')
            editor.select_char()
            editor.char_nudge_ms.set('1')
            editor.nudge_char('start', 1)
            self.assertAlmostEqual(owner.cues[0].spans[1][0], 1.201)
            editor.undo()
            self.assertAlmostEqual(owner.cues[0].spans[1][0], 1.2)
            self.assertTrue(preview.controls.winfo_manager())
            preview.toggle_controls()
            self.assertFalse(preview.controls.winfo_manager())
            preview.toggle_controls()
            self.assertTrue(preview.controls.winfo_manager())
        finally:
            if preview:
                preview.close()
            self.close_owner(root, owner)

    def test_add_delete_all_readd_and_save_current_preview(self):
        root, owner = self.make_owner()
        try:
            editor = owner.open_timeline(live=True)
            editor.window.withdraw()
            editor.add()
            self.assertEqual(len(owner.cues), 2)
            editor.text.delete('1.0', 'end')
            editor.text.insert('1.0', 'New line')
            self.assertTrue(editor.commit_line())
            self.assertEqual(owner.cues[1].text, 'New line')
            editor.tree.selection_set(*editor.tree.get_children())
            editor.delete()
            self.assertEqual(owner.cues, [])
            self.assertEqual(editor.text.get('1.0', 'end-1c'), '')
            editor.add()
            self.assertEqual(len(owner.cues), 1)
            editor.distribute()
            self.assertTrue(owner.cues[0].spans)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'edit.json'
                save_cues(path, owner.cues)
                self.assertEqual(load(path)[0].text, owner.cues[0].text)
                self.assertEqual([tuple(s) for s in load(path)[0].spans], owner.cues[0].spans)
        finally:
            self.close_owner(root, owner)

    def test_invalid_draft_stays_visible_and_stale_editor_cannot_replace_new_song(self):
        root, owner = self.make_owner()
        try:
            editor = owner.open_timeline(live=True)
            editor.window.withdraw()
            editor.times[2].set('invalid')
            self.assertFalse(editor.commit_line())
            self.assertEqual(editor.times[2].get(), 'invalid')
            self.assertEqual(owner.cues[0].end, 4)
            editor.times[2].set('4')
            owner.set_cues([Cue(0, 5, 'Other song')], 'external')
            editor.text.delete('1.0', 'end')
            editor.text.insert('1.0', 'Old edit')
            editor.commit_line()
            self.assertEqual(owner.cues[0].text, 'Other song')
            replacement = owner.open_timeline(live=True)
            replacement.window.withdraw()
            self.assertIsNot(editor, replacement)
        finally:
            self.close_owner(root, owner)

    def test_current_line_prefers_singing_over_an_early_displayed_line(self):
        root, owner = self.make_owner()
        try:
            owner.set_cues([Cue(0, 4, 'Now', sing_start=1), Cue(1, 7, 'Later', sing_start=5)], 'test')
            editor = owner.open_timeline(live=True)
            editor.window.withdraw()
            self.assertEqual(editor.selected, 0)
        finally:
            self.close_owner(root, owner)
if __name__ == '__main__':
    unittest.main()
