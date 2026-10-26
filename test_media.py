"""Real SNG timing, lyric rendering, encoded MP4/audio and preview control tests."""
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
import csv
import json
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import tkinter as tk
import bootstrap
import av
import numpy as np
from PIL import Image, ImageChops
import lyrics
from media import Background, Renderer, Style, default_font, export_mp4, export_video, input_audio
from engine import Settings
ROOT = Path(__file__).resolve().parent.parent

def source_video(path):
    with av.open(str(path), 'w') as out:
        video = out.add_stream('libx264', rate=25)
        video.width, video.height, video.pix_fmt = (320, 180, 'yuv420p')
        audio = out.add_stream('aac', rate=44100)
        audio.layout = 'stereo'
        for i in range(25):
            frame = av.VideoFrame.from_image(Image.new('RGB', (320, 180), 'red' if i < 12 else 'blue'))
            frame.pts, frame.time_base = (i, Fraction(1, 25))
            for packet in video.encode(frame):
                out.mux(packet)
        waveform = np.sin(np.arange(44100) * 2 * np.pi * 440 / 44100).astype('float32') * 0.2
        frame = av.AudioFrame.from_ndarray(np.stack([waveform, waveform]), format='fltp', layout='stereo')
        frame.sample_rate, frame.pts, frame.time_base = (44100, 0, Fraction(1, 44100))
        for packet in audio.encode(frame):
            out.mux(packet)
        for stream in (video, audio):
            for packet in stream.encode():
                out.mux(packet)

class MediaTests(unittest.TestCase):

    def test_transparent_renderer_keeps_straight_alpha_and_ignores_background(self):
        style = Style(font=default_font(), size=40, stroke_width=0, color='#ffffff')
        image = Renderer().render((640, 360), Image.new('RGB', (640, 360), 'green'), [lyrics.Cue(0, 1, 'Alpha 字幕')], 0.5, style, transparent=True)
        pixels = np.asarray(image)
        self.assertEqual(image.mode, 'RGBA')
        self.assertEqual(tuple(pixels[0, 0]), (0, 0, 0, 0))
        partial = (pixels[:, :, 3] > 20) & (pixels[:, :, 3] < 230)
        self.assertTrue(partial.any())
        np.testing.assert_array_equal(pixels[partial][:, :3], 255)

    def test_prores_4444_mov_alpha_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'transparent.mov'
            style = Style(font=default_font(), size=30, color='#00ff00')
            cues = [lyrics.Cue(0.2, 0.8, 'ProRes 透明')]
            export_video(path, output_format='prores4444', source='ignored-missing-background.mp4', cues=cues, style=style, duration=1, size=(640, 360), fps=25)
            with av.open(str(path)) as container:
                stream = container.streams.video[0]
                self.assertEqual(stream.codec_context.name, 'prores')
                self.assertEqual(stream.codec_context.profile, '4444')
                self.assertEqual(stream.codec_context.codec_tag, 'ap4h')
                self.assertTrue(stream.codec_context.format.name.startswith('yuva444'))
                self.assertEqual(stream.codec_context.colorspace, 1)
                self.assertEqual(stream.codec_context.color_primaries, 1)
                frames = list(container.decode(video=0))
                self.assertEqual(len(frames), 25)
                self.assertEqual(len(container.streams.audio), 0)
                for index in (0, 24):
                    self.assertFalse(frames[index].to_ndarray(format='rgba')[:, :, 3].any())
                pixels = frames[10].to_ndarray(format='rgba')
                alpha = pixels[:, :, 3]
                self.assertEqual(int(alpha.min()), 0)
                self.assertEqual(int(alpha.max()), 255)
                self.assertTrue(((alpha > 0) & (alpha < 255)).any())
                expected = np.asarray(Renderer().render((640, 360), None, cues, 0.4, style, transparent=True))
                self.assertLessEqual(np.abs(alpha.astype('int16') - expected[:, :, 3]).max(), 2)
                opaque_green = (alpha == 255) & (expected[:, :, 1] == 255)
                self.assertTrue(opaque_green.any())
                self.assertGreater(float(pixels[opaque_green][:, 1].mean()), 235)
                composite = Image.alpha_composite(Image.new('RGBA', (640, 360), 'magenta'), Image.fromarray(pixels))
                self.assertEqual(composite.getpixel((0, 0)), (255, 0, 255, 255))
            sound_path = Path(folder) / 'transparent_audio.mov'
            wave = np.sin(np.arange(44100) * 0.06).astype('float32') * 0.2
            song = SimpleNamespace(pcm=[np.stack((wave, wave), axis=1)])
            variant = SimpleNamespace(selected=[0], segmented=False, starts={0: 0})
            export_video(sound_path, output_format='prores4444', cues=cues, style=style, duration=0.4, size=(320, 180), fps=25, audio='sd3', song=song, variant=variant, settings=Settings(master=0.5, gains=[1]))
            with av.open(str(sound_path)) as container:
                self.assertEqual(container.streams.audio[0].codec_context.name, 'aac')
                self.assertGreater(sum((f.samples for f in container.decode(audio=0))), 17000)
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(InterruptedError):
                export_video(Path(folder) / 'cancel.mov', output_format='prores4444', cancel=cancel, duration=1, size=(320, 180), fps=25)
            self.assertFalse(list(Path(folder).glob('.*.rendering.mov')))
            with self.assertRaisesRegex(ValueError, '.mov'):
                export_video(Path(folder) / 'wrong.mp4', output_format='prores4444')

    def test_alpha_format_ui_passes_mov_selection_to_export(self):
        from presentation import Presentation, EXPORT_FORMATS
        root = tk.Tk()
        root.withdraw()
        engine = SimpleNamespace(position=lambda: 0, settings=Settings(), song=None, variant=None)
        app = SimpleNamespace(root=root, ready=True, song=None, engine=engine)
        controller = Presentation(app)
        try:
            controller.open()
            controller.window.withdraw()
            controller.output_format.set(next((k for k, v in EXPORT_FORMATS.items() if v == 'prores4444')))
            controller.format_changed()
            self.assertEqual(str(controller.green_checkbox['state']), 'disabled')
            self.assertIn('MOV', controller.export_button['text'])
            controller.enable_export.set(True)
            controller.export_toggle()
            with tempfile.TemporaryDirectory() as folder:
                with patch('presentation.filedialog.asksaveasfilename', return_value=str(Path(folder) / 'alpha.mov')) as chooser:
                    with patch('presentation.export_video') as encoder:
                        controller.export()
                        controller.export_thread.join(timeout=3)
                        self.assertEqual(encoder.call_args.kwargs['output_format'], 'prores4444')
                        self.assertEqual(chooser.call_args.kwargs['defaultextension'], '.mov')
        finally:
            controller.close()
            root.destroy()

    def test_real_mi3_line_times_and_template_roundtrip(self):
        for name, count, first, sing in [('CE053877', 51, 22.32, 24.82), ('CE000001', 77, 14.8, 17.3), ('CE010000', 56, 22.09, 24.59)]:
            data = lyrics.mi3_timing(ROOT / (name + '.MI3'))
            self.assertEqual(len(data['lines']), count)
            self.assertEqual(data['lines'][0]['display_seconds'], first)
            self.assertEqual(data['lines'][0]['sing_seconds'], sing)
            self.assertTrue(all((r['display_seconds'] <= r['sing_seconds'] <= r['clear_seconds'] for r in data['lines'])))
        with tempfile.TemporaryDirectory() as folder:
            paths = lyrics.export_template(ROOT / 'CE053877.MI3', folder)
            cues = lyrics.load(paths[0])
            self.assertEqual(len(cues), 51)
            self.assertEqual(cues[0].start, 22.32)
            self.assertEqual(cues[0].sing_start, 24.82)
            self.assertEqual(cues[0].end, 30.85)
            with paths[1].open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(float(rows[0]['clear_seconds']), 30.85)
            self.assertEqual(lyrics.load(paths[1])[0].sing_start, 24.82)
            self.assertEqual(lyrics.load(paths[2])[0].start, 24.82)
            self.assertEqual(lyrics.load(paths[3])[0].start, 22.32)
            with self.assertRaisesRegex(ValueError, 'already exist'):
                lyrics.export_template(ROOT / 'CE053877.MI3', folder)

    def test_lrc_enhanced_timing_offset_and_ass_karaoke(self):
        cues = lyrics.lrc('[offset:100]\n[00:01.00]<00:01.00>你<00:01.50>好\n[00:03.00]下一句\n[00:05.00]')
        self.assertAlmostEqual(cues[0].start, 0.9)
        self.assertAlmostEqual(cues[0].end, 2.9)
        self.assertEqual(cues[0].text, '你好')
        self.assertAlmostEqual(cues[0].spans[0][0], 0)
        self.assertAlmostEqual(cues[0].spans[0][1], 0.5)
        self.assertEqual(cues[0].spans[0][2:], (0, 1))
        repeated = lyrics.lrc('[00:01.00][00:05.00]<00:01.00>你<00:01.50>好')
        self.assertEqual(repeated[0].spans, repeated[1].spans)
        cues = lyrics.ass('[Events]\nFormat: Layer, Start, End, Style, Text\nDialogue: 0,0:00:01.00,0:00:03.00,Default,{\\k20}你{\\kf30}好\\N世界')
        self.assertEqual(cues[0].text, '你好\n世界')
        self.assertEqual(cues[0].spans[0], (0, 0.2, 0, 1))
        with self.assertRaises(ValueError):
            lyrics.lrc('没有打点的文本')

    def test_shared_renderer_style_and_exact_line_color_onset(self):
        style = Style(font=default_font(), size=34, bottom=20, stroke_width=2)
        cue = lyrics.Cue(0.2, 1, '同步 / Test', sing_start=0.6)
        renderer = Renderer()
        empty = renderer.render((640, 360), None, [cue], 0.1, style)
        before = renderer.render((640, 360), None, [cue], 0.4, style)
        after = renderer.render((640, 360), None, [cue], 0.8, style)
        self.assertEqual(empty.getpixel((0, 0)), (0, 255, 0))
        self.assertIsNotNone(ImageChops.difference(empty, before).getbbox())
        self.assertIsNotNone(ImageChops.difference(before, after).getbbox())
        self.assertEqual(renderer.render((640, 360), None, [cue], 1, style).tobytes(), empty.tobytes())

    def test_green_export_and_single_image_video(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            green = folder / 'green.mp4'
            export_mp4(green, green=True, cues=[lyrics.Cue(0.4, 1, '歌词')], style=Style(font=default_font(), size=30), duration=1, size=(640, 360), fps=25)
            with av.open(str(green)) as container:
                frames = list(container.decode(video=0))
                self.assertEqual(len(frames), 25)
                self.assertEqual(container.streams.video[0].codec_context.name, 'h264')
                self.assertEqual(len(container.streams.audio), 0)
                first = np.asarray(frames[0].to_image()).astype('int16')
                self.assertLess(np.abs(first[0, 0] - [0, 255, 0]).max(), 10)
                self.assertGreater(np.abs(np.asarray(frames[20].to_image()).astype('int16') - first).max(), 50)
            still = folder / 'still.png'
            Image.new('RGB', (320, 180), '#0030c0').save(still)
            movie = folder / 'still.mp4'
            export_mp4(movie, source=still, duration=0.4, size=(640, 360), fps=25)
            with av.open(str(movie)) as container:
                frames = list(container.decode(video=0))
                self.assertEqual(len(frames), 10)
                self.assertLess(np.abs(np.asarray(frames[5].to_image())[50, 50].astype('int16') - [0, 48, 192]).max(), 12)

    def test_video_random_seek_and_original_audio_export(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / 'source.mp4'
            source_video(source)
            video = Background(source)
            try:
                for timestamp, channel in [(0.1, 0), (0.8, 2), (0.2, 0)]:
                    pixel = video.at(timestamp).getpixel((10, 10))
                    self.assertGreater(pixel[channel], 200)
            finally:
                video.close()
            samples = input_audio(source)
            self.assertTrue(44100 <= len(samples) < 46000)
            self.assertGreater(float(np.std(samples)), 0.05)
            output = folder / 'copy.mp4'
            export_mp4(output, source=source, audio='video', duration=0.6, size=(320, 180), fps=25)
            with av.open(str(output)) as container:
                self.assertEqual(container.streams.audio[0].codec_context.name, 'aac')
                decoded = list(container.decode(audio=0))
                self.assertGreater(sum((frame.samples for frame in decoded)), 25000)

    def test_sd3_mix_export_and_cancellation_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            wave = np.sin(np.arange(44100) * 0.06).astype('float32') * 0.2
            song = SimpleNamespace(pcm=[np.stack((wave, wave), axis=1)])
            variant = SimpleNamespace(selected=[0], segmented=False, starts={0: 0})
            path = folder / 'audio.mp4'
            export_mp4(path, green=True, duration=0.2, size=(320, 180), fps=25, audio='sd3', song=song, variant=variant, settings=Settings(master=0.5, gains=[1]))
            with av.open(str(path)) as container:
                frames = list(container.decode(audio=0))
                self.assertGreater(float(np.std(frames[1].to_ndarray())), 0.02)
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(InterruptedError):
                export_mp4(folder / 'cancelled.mp4', cancel=cancel, duration=1, size=(320, 180), fps=25)
            self.assertFalse((folder / 'cancelled.mp4').exists())
            self.assertFalse(list(folder.glob('.*.rendering.mp4')))
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'already exist'):
                export_mp4(path, duration=1)
            self.assertEqual(path.read_bytes(), original)

    def test_preview_and_export_switches_and_shared_clock(self):
        from presentation import Presentation
        root = tk.Tk()
        root.withdraw()
        engine = SimpleNamespace(position=lambda: 24.82, settings=Settings(), song=None, variant=None, command=lambda *args: None)
        app = SimpleNamespace(root=root, ready=True, song=None, engine=engine, play=lambda: None)
        controller = Presentation(app)
        try:
            controller.open()
            controller.window.withdraw()
            self.assertEqual(controller.position(), 24.82)
            controller.enable_preview.set(False)
            controller.preview(False)
            self.assertEqual(controller.previews, [])
            controller.enable_export.set(False)
            with patch('presentation.export_video', side_effect=AssertionError('should not export')):
                controller.export()
                self.assertIsNone(controller.export_thread)
            self.assertEqual(str(controller.export_button['state']), 'disabled')
            controller.enable_export.set(True)
            controller.export_toggle()
            self.assertEqual(str(controller.export_button['state']), 'normal')
            controller.follow.set(False)
            controller.follow_changed()
            self.assertEqual(controller.position(), 24.82)
            controller.seek(2)
            self.assertEqual(controller.position(), 2)
        finally:
            controller.close()
            root.destroy()

    def test_two_live_windows_pause_seek_and_style(self):
        from presentation import Presentation
        from PIL import ImageTk
        root = tk.Tk()
        root.withdraw()
        clock = [22.4]

        def command(name, value):
            if name == 'seek':
                clock[0] = value
        engine = SimpleNamespace(position=lambda: clock[0], settings=Settings(), song=None, variant=None, command=command)
        app = SimpleNamespace(root=root, ready=True, song=None, engine=engine, play=lambda: None)
        controller = Presentation(app)

        def wait(predicate):
            end = time.monotonic() + 4
            while not predicate() and time.monotonic() < end:
                root.update()
                time.sleep(0.01)
            self.assertTrue(predicate())
        try:
            with tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / 'background.png'
                Image.new('RGB', (640, 360), 'blue').save(source)
                controller.source.set(str(source))
                controller.cues = lyrics.mi3_cues(ROOT / 'CE053877.MI3')
                controller.resolution.set('640x360')
                controller.font_size.set('28')
                controller.preview(False)
                controller.preview(True)
                for window in controller.previews:
                    window.window.geometry('640x360')
                    window.window.update_idletasks()
                wait(lambda: all((hasattr(p, 'photo') and p.photo.width() > 100 and (p.photo.width() <= p.canvas.winfo_width()) and (p.photo.height() <= p.canvas.winfo_height()) and (abs(p.photo.width() / p.photo.height() - 640 / 360) < 0.01) for p in controller.previews)))
                first = ImageTk.getimage(controller.previews[1].photo).convert('RGB')
                controller.seek(25)
                wait(lambda: controller.previews[1].key[2] == 750)
                end = time.monotonic() + 3
                changed = False
                while not changed and time.monotonic() < end:
                    root.update()
                    image = ImageTk.getimage(controller.previews[1].photo).convert('RGB')
                    changed = image.size == first.size and image.tobytes() != first.tobytes()
                    time.sleep(0.01)
                self.assertTrue(changed)
                controller.seek(0)

                def cleared():
                    image = np.asarray(ImageTk.getimage(controller.previews[1].photo).convert('RGB'))
                    return (image == [0, 255, 0]).all()
                wait(cleared)
                controller.enable_preview.set(False)
                workers = [p.worker for p in controller.previews]
                controller.preview_toggle()
                self.assertEqual(controller.previews, [])
                self.assertTrue(all((not w.is_alive() for w in workers)))
        finally:
            controller.close()
            root.destroy()
if __name__ == '__main__':
    unittest.main(verbosity=2)
