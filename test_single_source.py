"""Single-source playback/export and manually entered PCM offset regression."""
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import av
import numpy as np
from song import load_song, RATE, decode_audio
from engine import PlayerEngine, Settings, playback_duration
from media import export_video
from test_audio_input import audio_file, midi_file
from test_player import FakeStream, FakeMidi, eventually
ROOT = Path(__file__).resolve().parent.parent

class SingleSourceTests(unittest.TestCase):

    def test_only_sd3_and_empty_input(self):
        with self.assertRaises(ValueError):
            load_song()
        song = load_song(sd3=ROOT / 'CE000001.SD3')
        self.assertIsNone(song.mi3)
        self.assertTrue(song.audio_override)
        self.assertEqual(len(song.pcm), 2)
        self.assertFalse(song.variants[0].events)

    def test_only_audio_gui_load_play_and_offset_duration(self):
        from app import App, MODES
        with tempfile.TemporaryDirectory() as folder:
            sound = Path(folder) / 'solo.wav'
            audio_file(sound)
            root = tk.Tk()
            root.withdraw()
            engine = PlayerEngine(stream_factory=FakeStream, midi_factory=FakeMidi)
            player = App(root, engine=engine)
            try:
                with patch('app.messagebox.showerror', side_effect=AssertionError):
                    player.sd3_path.set(str(sound))
                    player.offset_audio.set('12345.5')
                    player.load()
                    end = time.monotonic() + 4
                    while not player.ready and time.monotonic() < end:
                        root.update()
                        time.sleep(0.01)
                    self.assertTrue(player.ready)
                    self.assertEqual(MODES[player.mode_var.get()], 'audio')
                    self.assertAlmostEqual(engine.settings.audio_offset, 12.3455)
                    self.assertAlmostEqual(engine.duration, 12.8455)
                    player.open_presentation()
                    self.assertAlmostEqual(float(player.presentation.duration.get()), 12.8455, delta=0.001)
                    self.assertTrue(player.presentation.audio.get())
                    player.play()
                    eventually(lambda: engine.playing)
                    self.assertTrue(engine.stream.active)
                    engine.command('pause')
                    eventually(lambda: not engine.playing)
                    player.offset_audio.set('-100')
                    player.apply()
                    end = time.monotonic() + 3
                    while not player.ready and time.monotonic() < end:
                        root.update()
                        time.sleep(0.01)
                    self.assertTrue(player.ready)
                    self.assertAlmostEqual(engine.duration, 0.4)
                    self.assertAlmostEqual(float(player.presentation.duration.get()), 0.4)
            finally:
                player.close()

    def test_only_audio_export_uses_signed_pcm_offset(self):
        with tempfile.TemporaryDirectory() as folder:
            sound = Path(folder) / 'solo.flac'
            audio_file(sound, 'flac')
            song = load_song(sd3=sound)
            variant = song.variants[0]
            for offset, expected in [(0.1, 0.6), (-0.1, 0.4)]:
                settings = Settings(mode='audio', audio_offset=offset, master=1)
                self.assertAlmostEqual(playback_duration(song, variant, settings), expected)
                target = Path(folder) / f'mix_{offset}.mp4'
                export_video(target, duration=expected, size=(320, 180), fps=25, audio='sd3', song=song, variant=variant, settings=settings)
                pcm = decode_audio(str(target))
                if offset > 0:
                    self.assertLess(np.sqrt(np.mean(pcm[:int(0.07 * RATE)] ** 2)), 0.001)
                self.assertGreater(np.sqrt(np.mean(pcm[int(0.15 * RATE):int(0.25 * RATE)] ** 2)), 0.05)

    def test_only_midi_play_and_silent_video_export(self):
        with tempfile.TemporaryDirectory() as folder:
            music = Path(folder) / 'solo.mid'
            midi_file(music)
            song = load_song(music)
            engine = PlayerEngine(stream_factory=FakeStream, midi_factory=FakeMidi)
            try:
                engine.configure(song, 0, Settings(mode='midi', midi_devices=(0,), midi_sources=(0,)))
                eventually(lambda: engine.song is song and engine.stream is not None)
                engine.command('play')
                eventually(lambda: engine.playing)
                engine._callback(np.zeros((512, 2), dtype='float32'), 512, SimpleNamespace(outputBufferDacTime=100, currentTime=100), None)
                eventually(lambda: any((m[:1] == b'\x90' for m in engine.outputs[0].sent)))
                target = Path(folder) / 'midi_only.mp4'
                export_video(target, duration=0.2, size=(320, 180), fps=25, audio='none', song=song, variant=song.variants[0], settings=engine.settings)
                with av.open(str(target)) as video:
                    self.assertEqual(len(video.streams.audio), 0)
                    self.assertEqual(len(list(video.decode(video=0))), 5)
            finally:
                engine.close()

    def test_only_mi3_chooses_midi_mode(self):
        from app import App, MODES
        root = tk.Tk()
        root.withdraw()
        player = App(root, engine=PlayerEngine(stream_factory=FakeStream, midi_factory=FakeMidi))
        try:
            player.on_loaded(load_song(ROOT / 'CE000001.MI3'))
            self.assertEqual(MODES[player.mode_var.get()], 'midi')
        finally:
            player.close()
if __name__ == '__main__':
    unittest.main()
