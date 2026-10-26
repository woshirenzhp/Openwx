"""External audio decoding, arbitrary pairing and exported mix integration."""
from pathlib import Path
from fractions import Fraction
import tempfile
import unittest
from unittest.mock import patch
import tkinter as tk
import bootstrap
import av
import mido
import numpy as np
from song import load_song, decode_audio, RATE
from engine import mix_block, selected_tracks, Settings
from media import export_video
ROOT = Path(__file__).resolve().parent.parent

def midi_file(path):
    midi = mido.MidiFile()
    midi.tracks.append(mido.MidiTrack([mido.Message('note_on', note=60, velocity=80), mido.Message('note_off', note=60, time=480)]))
    midi.save(path)

def audio_file(path, codec='pcm_s16le', rate=48000):
    with av.open(str(path), 'w') as output:
        stream = output.add_stream(codec, rate=rate)
        stream.layout = 'mono'
        fmt = stream.codec_context.format.name
        wave = 0.2 * np.sin(np.arange(rate // 2) * 2 * np.pi * 440 / rate)
        if fmt.startswith('s16'):
            wave = (wave * 32767).astype('int16')
        elif fmt.startswith('s32'):
            wave = (wave * 2147483647).astype('int32')
        else:
            wave = wave.astype('float32')
        frame = av.AudioFrame.from_ndarray(wave[None, :], format=fmt, layout='mono')
        frame.sample_rate, frame.pts, frame.time_base = (rate, 0, Fraction(1, rate))
        for packet in stream.encode(frame):
            output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)

class AudioInputTests(unittest.TestCase):

    def test_real_wav_aac_mp3_flac_alac_decode_and_resample(self):
        with tempfile.TemporaryDirectory() as folder:
            for extension, codec in [('wav', 'pcm_s16le'), ('aac', 'aac'), ('mp3', 'mp3'), ('flac', 'flac'), ('m4a', 'alac')]:
                with self.subTest(format=extension):
                    path = Path(folder) / ('tone.' + extension)
                    audio_file(path, codec)
                    pcm = decode_audio(str(path))
                    self.assertEqual(pcm.dtype, np.float32)
                    self.assertEqual(pcm.shape[1], 2)
                    self.assertTrue(pcm.flags.c_contiguous)
                    self.assertLess(abs(len(pcm) / RATE - 0.5), 0.06)
                    self.assertGreater(np.sqrt(np.mean(pcm ** 2)), 0.05)
                    np.testing.assert_allclose(pcm[:, 0], pcm[:, 1], atol=1e-06)
                    spectrum = np.abs(np.fft.rfft(pcm[:, 0]))
                    peak = np.argmax(spectrum) * RATE / len(pcm)
                    self.assertLess(abs(peak - 440), 6)
            self.assertEqual(av.Codec('ape', 'r').name, 'ape')

    def test_midi_audio_pair_and_multiple_midi_preserve_tracks(self):
        with tempfile.TemporaryDirectory() as folder:
            music = Path(folder) / 'arbitrary-name.midi'
            second = Path(folder) / 'second.mid'
            sound = Path(folder) / 'unrelated-name.wav'
            midi_file(music)
            midi_file(second)
            audio_file(sound)
            for paths, count in [(music, 1), ([music, second], 2)]:
                song = load_song(paths, sound)
                variant = song.variants[0]
                self.assertEqual(variant.label, 'SMF')
                self.assertEqual(len(variant.parts), count)
                self.assertEqual(variant.note_count, count)
                self.assertEqual(selected_tracks(song, variant, 'auto'), [0])
                self.assertEqual(selected_tracks(song, variant, 'midi'), [])
                self.assertTrue(song.audio_override)
                self.assertEqual(song.warnings, [])

    def test_mi3_external_audio_ignores_native_gates_with_offset(self):
        with tempfile.TemporaryDirectory() as folder:
            sound = Path(folder) / 'custom.wav'
            audio_file(sound)
            song = load_song(ROOT / 'CE053877.MI3', sound)
            variant = song.variants[0]
            self.assertEqual(song.warnings, [])
            variant.starts[0] = 100
            variant.segmented = True
            tracks = selected_tracks(song, variant, 'auto')
            settings = Settings(audio_offset=0.1, master=1)
            output = mix_block(song, variant, tracks, 0, RATE // 2, settings)
            self.assertFalse(output[:4410].any())
            np.testing.assert_array_equal(output[4410:], song.pcm[0][:len(output) - 4410])
            settings.audio_offset = -0.1
            output = mix_block(song, variant, tracks, 0, 1000, settings)
            np.testing.assert_array_equal(output, song.pcm[0][4410:5410])

    def test_midi_can_use_all_native_sd3_tracks(self):
        with tempfile.TemporaryDirectory() as folder:
            music = Path(folder) / 'unrelated.mid'
            midi_file(music)
            song = load_song(music, ROOT / 'CE000001.SD3')
            self.assertTrue(song.audio_override)
            self.assertEqual(selected_tracks(song, song.variants[0], 'auto'), [0, 1])
            self.assertEqual(song.warnings, [])
            self.assertGreater(len(song.pcm[0]), RATE)

    def test_external_mix_reaches_export_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            music, sound = (Path(folder) / 'song.mid', Path(folder) / 'sound.wav')
            midi_file(music)
            audio_file(sound)
            song = load_song(music, sound)
            target = Path(folder) / 'mix.mp4'
            export_video(target, duration=0.4, size=(320, 180), fps=25, audio='sd3', song=song, variant=song.variants[0], settings=Settings(master=0.5))
            pcm = decode_audio(str(target))
            self.assertGreater(np.sqrt(np.mean(pcm ** 2)), 0.02)
            self.assertLess(np.sqrt(np.mean(pcm ** 2)), 0.08)

    def test_gui_choosers_and_audio_pair_retained(self):
        from app import App, MODES
        from test_player import FakeStream, FakeMidi
        from engine import PlayerEngine
        with tempfile.TemporaryDirectory() as folder:
            music, sound = (Path(folder) / 'song.mid', Path(folder) / 'sound.wav')
            midi_file(music)
            audio_file(sound)
            root = tk.Tk()
            root.withdraw()
            app = App(root, engine=PlayerEngine(stream_factory=FakeStream, midi_factory=FakeMidi))
            try:
                app.sd3_path.set(str(sound))
                with patch('app.filedialog.askopenfilename', return_value=str(music)) as chooser:
                    app.browse(app.mi3_path, '.MI3')
                    self.assertIn('*.mid', str(chooser.call_args))
                self.assertEqual(app.sd3_path.get(), str(sound))
                with patch('app.filedialog.askopenfilename', return_value=str(sound)) as chooser:
                    app.browse(app.sd3_path, '.SD3')
                    for ext in ('wav', 'aac', 'mp3', 'flac', 'ape', 'alac', 'm4a'):
                        self.assertIn('*.' + ext, str(chooser.call_args))
                app.on_loaded(load_song(music, sound))
                self.assertEqual(MODES[app.mode_var.get()], 'auto')
                self.assertEqual(app.sd3_path.get(), str(sound))
                self.assertEqual(len(app.gain_vars), 1)
                self.assertEqual(len(app.midi_boxes), 4)
            finally:
                app.close()
if __name__ == '__main__':
    unittest.main()
