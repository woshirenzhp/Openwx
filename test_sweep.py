"""Verify spatial left-to-right coloring, character timing, seek and encoded alpha."""
from pathlib import Path
import tempfile
import unittest
import bootstrap
import av
import numpy as np
from lyrics import Cue
from media import Renderer, Style, default_font, export_video

class SweepTests(unittest.TestCase):

    def test_linear_spatial_boundary_and_unchanged_alpha(self):
        renderer = Renderer()
        style = Style(font=default_font(), size=64, stroke_width=3, bottom=25)
        cue = Cue(0, 3, '田', [(0, 2, 0, 1)])
        size = (320, 180)
        before = np.asarray(renderer.render(size, None, [cue], 0, style, transparent=True))
        after = np.asarray(renderer.render(size, None, [cue], 2, style, transparent=True))
        font = renderer.fonts[style.font, style.size]
        ink = font.getbbox('田')
        x = round((size[0] - font.getlength('田')) / 2)
        for progress in (0.25, 0.5, 0.75):
            frame = np.asarray(renderer.render(size, None, [cue], progress * 2, style, transparent=True))
            np.testing.assert_array_equal(frame[:, :, 3], before[:, :, 3])
            edge = x + round(ink[0] + (ink[2] - ink[0]) * progress)
            expected = before.copy()
            expected[:, :edge] = after[:, :edge]
            np.testing.assert_array_equal(frame, expected)
            self.assertTrue(np.any(frame != before))
            self.assertTrue(np.any(frame != after))
        a = renderer.render(size, None, [cue], 0.5, style)
        renderer.render(size, None, [cue], 1.5, style)
        np.testing.assert_array_equal(np.asarray(a), np.asarray(renderer.render(size, None, [cue], 0.5, style)))

    def test_each_character_waits_for_its_interval_and_mov_keeps_alpha(self):
        renderer = Renderer()
        style = Style(font=default_font(), size=48, stroke_width=0, bottom=30)
        cues = [Cue(0, 3, '田田', [(0, 1, 0, 1), (1, 2, 1, 2)], sing_start=0)]
        at_half = np.asarray(renderer.render((320, 180), None, cues, 0.5, style, transparent=True))
        full_first = np.asarray(renderer.render((320, 180), None, cues, 1, style, transparent=True))
        np.testing.assert_array_equal(at_half[:, 160:], full_first[:, 160:])
        self.assertTrue(np.any(at_half[:, :160] != full_first[:, :160]))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sweep.mov'
            export_video(path, cues=cues, style=style, duration=1, size=(320, 180), fps=24, output_format='prores4444')
            with av.open(str(path)) as container:
                frames = list(container.decode(video=0))
                actual = frames[12].to_ndarray(format='rgba')
                self.assertLessEqual(np.abs(actual[:, :, 3].astype('int16') - at_half[:, :, 3]).max(), 2)
                opaque = at_half[:, :, 3] == 255
                yellow = opaque & (at_half[:, :, 2] == 0)
                white = opaque & (at_half[:, :, 2] == 255)
                self.assertTrue(yellow.any() and white.any())
                self.assertLess(float(actual[yellow][:, 2].mean()), 15)
                self.assertGreater(float(actual[white][:, 2].mean()), 240)
if __name__ == '__main__':
    unittest.main()
