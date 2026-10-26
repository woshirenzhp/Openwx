"""Project persistence, portable assets, language-neutral settings and GUI restore."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image
import projects
from lyrics import Cue
from song import load_song
from app import App, MODES
from engine import PlayerEngine
from test_audio_input import audio_file, midi_file
from test_player import FakeStream, FakeMidi

class ProjectTests(unittest.TestCase):

    def test_new_extensions_and_legacy_projects_remain_readable(self):
        self.assertEqual(projects.SUFFIXES['.opw'], 'references')
        self.assertEqual(projects.SUFFIXES['.opx'], 'packed')
        with tempfile.TemporaryDirectory() as folder:
            root, app = self.make_app()
            try:
                self.prepare(app, self.fixtures(folder))
                snapshot, paths = app.projects.capture()
                for legacy, current in (('.mi3proj', '.opw'), ('.mi3pack', '.opx')):
                    old = Path(folder) / ('old' + legacy)
                    projects.write(old, snapshot, paths)
                    data, resolved = projects.read(old)
                    self.assertEqual(data['kind'], projects.SUFFIXES[current])
                    self.assertTrue(resolved)
                    app.projects.current = str(old)
                    with patch('project_ui.messagebox.showerror') as errors:
                        app.projects.save(reuse=True)
                        self.wait(root, lambda: not app.projects.busy)
                        errors.assert_not_called()
                    self.assertTrue(old.with_suffix(current).is_file())
            finally:
                self.close_app(root, app)

    def make_app(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root, engine=PlayerEngine(stream_factory=FakeStream, midi_factory=FakeMidi))
        return (root, app)

    def close_app(self, root, app):
        if app.presentation:
            app.presentation.close()
        root.update_idletasks()
        for job in root.tk.call('after', 'info'):
            root.after_cancel(job)
        app.close()

    def wait(self, root, predicate):
        end = time.monotonic() + 8
        while not predicate() and time.monotonic() < end:
            root.update()
            time.sleep(0.01)
        self.assertTrue(predicate())

    def fixtures(self, folder):
        folder = Path(folder)
        music = folder / 'first.mid'
        second = folder / 'second.mid'
        audio = folder / 'backing.wav'
        image = folder / 'background.png'
        midi_file(music)
        midi_file(second)
        audio_file(audio)
        Image.new('RGB', (320, 180), 'blue').save(image)
        return (music, second, audio, image)

    def prepare(self, app, files):
        music, second, audio, image = files
        app.mi3_path.set(str(music))
        app.sd3_path.set(str(audio))
        app.on_loaded(load_song([music, second], audio))
        app.offset_audio.set('125')
        app.offset_midi.set('-20')
        app.master_var.set(43)
        app.gain_vars[0].set(61)
        app.route_maps[0] = {0: {0, 3}, 1: {1, 2}}
        p = app.projects.presentation()
        p.source.set(str(image))
        p.font_size.set('66')
        p.colors['highlight'].set('#55aaff')
        p.filter_numeric.set(True)
        p.follow.set(False)
        p.local_position = 0.234
        p.duration.set('12.75')
        p.lyric_ms.set('75')
        p.video_ms.set('-25')
        p.timing_enabled.set(True)
        p.timing_vars['advance_ms'].set('3300')
        p.set_cues([Cue(1, 5, 'A[0125]B', [(0.123, 0.456, 0, 1), (1.234, 2.345, 7, 8)], 1.1, 'manual')], 'test')
        return app.projects.capture()

    def test_reference_json_keeps_lyrics_settings_relative_paths_and_multiple_midi(self):
        with tempfile.TemporaryDirectory() as folder:
            root, app = self.make_app()
            try:
                snapshot, paths = self.prepare(app, self.fixtures(folder))
                path = Path(folder) / 'song.opw'
                projects.write(path, snapshot, paths)
                raw = json.loads(path.read_text('utf-8'))
                self.assertEqual(raw['kind'], 'references')
                self.assertEqual(len(raw['links']['music']), 2)
                self.assertEqual(raw['lyrics'][0]['text'], 'A[0125]B')
                self.assertAlmostEqual(raw['lyrics'][0]['spans'][1][0], 1.234)
                self.assertLess(path.stat().st_size, 20000)
                data, resolved = projects.read(path)
                self.assertEqual(data['playback']['routes'], {'0': {'0': [0, 3], '1': [1, 2]}})
                self.assertEqual(set(resolved), set(paths))
                self.assertFalse(Path(data['resources'][0]['path']).is_absolute())
            finally:
                self.close_app(root, app)

    def test_packed_project_survives_deleting_original_media_and_same_name_collisions(self):
        with tempfile.TemporaryDirectory() as folder:
            root, app = self.make_app()
            try:
                files = self.fixtures(folder)
                other = Path(folder) / 'other'
                other.mkdir()
                same = other / 'first.mid'
                same.write_bytes(files[1].read_bytes())
                files = (files[0], same, files[2], files[3])
                snapshot, paths = self.prepare(app, files)
                path = Path(folder) / 'packed.opx'
                projects.write(path, snapshot, paths)
                for file in files:
                    file.unlink()
                data, resolved = projects.read(path, cache_root=Path(folder) / 'cache')
                self.assertTrue(all((p.is_file() for p in resolved.values())))
                self.assertEqual([resolved[r].name for r in data['links']['music']], ['first.mid', 'first.mid'])
                music = [resolved[r] for r in data['links']['music']]
                song = load_song(music, resolved[data['links']['audio']])
                self.assertEqual(song.variants[0].note_count, 2)
                self.assertEqual(song.music_paths, music)
                self.assertTrue(all(('absolute_path' not in item for item in data['resources'])))
            finally:
                self.close_app(root, app)

    def test_gui_async_save_open_restores_routes_offsets_raw_lyrics_and_export_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            root, app = self.make_app()
            try:
                self.prepare(app, self.fixtures(folder))
                path = Path(folder) / 'gui.opw'
                with patch('project_ui.messagebox.showerror') as errors:
                    app.projects.save(path=path)
                    self.wait(root, lambda: not app.projects.busy)
                    self.assertTrue(path.exists())
                    self.assertFalse(errors.called)
                    app.projects.presentation().set_cues([Cue(0, 3, 'changed')], 'test')
                    app.projects.open(path)
                    self.wait(root, lambda: not app.projects.busy and app.ready and (app.projects.pending_ready is None))
                    self.assertFalse(errors.called, errors.call_args)
                p = app.presentation
                self.assertEqual(len(app.song.music_paths), 2)
                self.assertEqual(app.route_maps[0], {0: {0, 3}, 1: {1, 2}})
                self.assertEqual(app.engine.settings.audio_offset, 0.125)
                self.assertEqual(app.engine.settings.midi_offset, -0.02)
                self.assertAlmostEqual(app.engine.settings.master, 0.43)
                self.assertAlmostEqual(app.engine.settings.gains[0], 0.61)
                self.assertEqual(p.cues[0].text, 'A[0125]B')
                self.assertTrue(p.filter_numeric.get())
                self.assertEqual(p.style.size, 66)
                self.assertEqual(p.style.advance_ms, 3300)
                self.assertEqual(p.style.highlight, '#55aaff')
                self.assertEqual(float(p.duration.get()), 12.75)
                self.assertFalse(app.engine.playing)
                self.wait(root, lambda: abs(app.engine.position() - 0.234) < 0.001)
            finally:
                self.close_app(root, app)

    def test_missing_reference_can_relink_without_changing_current_session_on_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            root, app = self.make_app()
            try:
                files = self.fixtures(folder)
                snapshot, paths = self.prepare(app, files)
                path = Path(folder) / 'missing.opw'
                projects.write(path, snapshot, paths)
                missing = files[2]
                replacement = Path(folder) / 'renamed.wav'
                missing.rename(replacement)
                old = app.song
                with patch('project_ui.filedialog.askopenfilename', return_value=''):
                    app.projects.open(path)
                    self.wait(root, lambda: not app.projects.busy)
                self.assertIs(app.song, old)
                with patch('project_ui.filedialog.askopenfilename', return_value=str(replacement)), patch('project_ui.messagebox.showerror') as errors:
                    app.projects.open(path)
                    self.wait(root, lambda: not app.projects.busy and app.song is not old)
                    self.assertFalse(errors.called, errors.call_args)
                self.assertEqual(app.song.sd3, replacement)
            finally:
                self.close_app(root, app)

    def test_lyrics_only_project_does_not_need_music_and_unloads_previous_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root, app = self.make_app()
            try:
                p = app.projects.presentation()
                p.set_cues([Cue(0, 3, 'Only lyrics')], 'test')
                snapshot, paths = app.projects.capture()
                path = Path(folder) / 'lyrics.opw'
                projects.write(path, snapshot, paths)
                files = self.fixtures(folder)
                self.prepare(app, files)
                with patch('project_ui.messagebox.showerror') as errors:
                    app.projects.open(path)
                    self.wait(root, lambda: not app.projects.busy and app.song is None)
                    self.assertFalse(errors.called, errors.call_args)
                self.assertEqual(app.presentation.cues[0].text, 'Only lyrics')
                self.assertFalse(app.ready)
                self.wait(root, lambda: app.engine.song is None)
            finally:
                self.close_app(root, app)

    def test_malicious_archive_paths_hashes_and_versions_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root, app = self.make_app()
            try:
                snapshot, paths = self.prepare(app, self.fixtures(folder))
                packed = Path(folder) / 'base.opx'
                projects.write(packed, snapshot, paths)
                for attack in ('extra', 'hash', 'version'):
                    target = Path(folder) / (attack + '.opx')
                    with zipfile.ZipFile(packed) as source, zipfile.ZipFile(target, 'w') as out:
                        data = json.loads(source.read('manifest.json'))
                        if attack == 'version':
                            data['version'] = 999
                        for info in source.infolist():
                            if info.filename == 'manifest.json':
                                continue
                            content = source.read(info)
                            if attack == 'hash' and info.filename == data['resources'][0]['path']:
                                content = b'X' + content[1:]
                            out.writestr(info.filename, content)
                        out.writestr('manifest.json', json.dumps(data))
                        if attack == 'extra':
                            out.writestr('../outside.txt', 'bad')
                    with self.assertRaises(ValueError):
                        projects.read(target, cache_root=Path(folder) / 'cache')
                    self.assertFalse((Path(folder) / 'outside.txt').exists())
            finally:
                self.close_app(root, app)

    def test_missing_hardware_is_not_reassigned_to_an_unrelated_midi_output(self):
        root, app = self.make_app()
        try:
            warnings = []
            lookup = {'OFF': None, '0: Different synth': 0}
            label = app.projects.choose_device({'id': 0, 'name': 'Missing synth'}, lookup, warnings)
            self.assertEqual(label, 'OFF')
            self.assertTrue(warnings)
        finally:
            self.close_app(root, app)

    def test_packed_cache_is_reused_and_tampered_cache_is_repaired_without_deleting_old_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root, app = self.make_app()
            try:
                snapshot, paths = self.prepare(app, self.fixtures(folder))
                path = Path(folder) / 'cached.opx'
                projects.write(path, snapshot, paths)
                data, first = projects.read(path, cache_root=Path(folder) / 'cache')
                _, second = projects.read(path, cache_root=Path(folder) / 'cache')
                self.assertEqual(first, second)
                rid = data['links']['music'][0]
                old = first[rid]
                original = old.read_bytes()
                old.write_bytes(b'X' + original[1:])
                _, repaired = projects.read(path, cache_root=Path(folder) / 'cache')
                self.assertEqual(repaired[rid].read_bytes(), original)
                self.assertNotEqual(repaired[rid], old)
                self.assertTrue(old.exists())
            finally:
                self.close_app(root, app)

    def test_live_draft_is_flushed_into_project_snapshot(self):
        root, app = self.make_app()
        try:
            p = app.projects.presentation()
            p.set_cues([Cue(0, 3, 'Before')], 'test')
            editor = p.open_timeline(live=True)
            editor.window.withdraw()
            editor.text.delete('1.0', 'end')
            editor.text.insert('1.0', 'After')
            snapshot, paths = app.projects.capture()
            self.assertEqual(snapshot['lyrics'][0]['text'], 'After')
        finally:
            self.close_app(root, app)

    def test_main_and_independent_preview_positions_are_saved_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            root, app = self.make_app()
            try:
                self.prepare(app, self.fixtures(folder))
                self.wait(root, lambda: app.ready)
                app.engine.command('seek', 0.125)
                self.wait(root, lambda: abs(app.engine.position() - 0.125) < 0.001)
                data, paths = app.projects.capture()
                self.assertAlmostEqual(data['position'], 0.125, delta=1 / 44100)
                self.assertAlmostEqual(data['presentation']['local_position'], 0.234)
            finally:
                self.close_app(root, app)
if __name__ == '__main__':
    unittest.main()
