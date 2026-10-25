"""Shared renderer and offline H.264 MP4 / transparent ProRes 4444 MOV export."""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import math
import os
import threading
import uuid
import bootstrap
import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

def default_font():
    bundled = Path(__file__).parent / 'fonts' / 'UDRGMZtk.ttf'
    if bundled.exists():
        return str(bundled)
    folder = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for name in ('msyh.ttc', 'YuGothM.ttc', 'meiryo.ttc', 'arial.ttf'):
        if (folder / name).exists():
            return str(folder / name)
    return ''

@dataclass
class Style:
    font: str = ''
    size: int = 54
    color: str = '#ffffff'
    highlight: str = '#ffff00'
    stroke: str = '#000000'
    stroke_width: int = 3
    background: str = '#00ff00'
    bottom: int = 50
    page_lines: int = 2
    immediate_line_change: bool = False

class Renderer:

    def __init__(self):
        self.fonts = {}
        self.glyphs = {}
        self.page_key = None
        self.pages = []

    @staticmethod
    def row_complete(cue, indices):
        """Last visible character's highlight completion, independent of clear time."""
        times = []
        for index in indices:
            if cue.text[index].isspace():
                continue
            if not cue.spans:
                times.append(cue.sing_start if cue.sing_start is not None else cue.end)
                continue
            span = next((s for s in cue.spans if s[2] <= index < s[3]), None)
            if span is None:
                times.append(cue.end)
            else:
                a, b, left, right = span
                times.append(cue.start + a + (b - a) * (index + 1 - left) / (right - left))
        return max(times, default=cue.start)

    def page_at(self, cues, position, font, font_key, width, height, style):
        signature = tuple(((c.start, c.end, c.text, c.sing_start, tuple((tuple(s) for s in c.spans))) for c in cues))
        capacity = max(1, min(style.page_lines, max(1, (height - style.bottom) // math.ceil(style.size * 1.45))))
        key = (signature, font_key, width, capacity, style.stroke_width, style.immediate_line_change)
        if key != self.page_key:
            rows = []
            margin = max(20, style.stroke_width * 3)
            for cue in sorted(cues, key=lambda c: c.start):
                if not cue.text:
                    continue
                line, indices = ('', [])
                for index, char in enumerate(cue.text):
                    if char == '\n' or (line and font.getlength(line + char) > width - 2 * margin):
                        rows.append((cue, line, indices))
                        line, indices = ('', [])
                        if char == '\n':
                            continue
                    line += char
                    indices.append(index)
                if indices:
                    rows.append((cue, line, indices))
            step = 1 if style.immediate_line_change else capacity
            pages = [rows[i:i + capacity] for i in range(0, len(rows), step)]

            def sentence_end(row):
                cue, _, indices = row
                return self.row_complete(cue, indices) if cue.spans else cue.end
            starts = []
            for i, page in enumerate(pages):
                start = min((c.start for c, _, _ in page))
                if i:
                    if style.immediate_line_change:
                        start = max(starts[-1], sentence_end(rows[i - 1]))
                    else:
                        start = max(start, starts[-1], max((self.row_complete(c, indices) for c, _, indices in pages[i - 1])))
                starts.append(start)
            self.pages = [(start, starts[i + 1] if i + 1 < len(starts) else max(start, sentence_end(rows[-1])) if style.immediate_line_change else max((max(c.end, self.row_complete(c, indices)) for c, _, indices in pages[i])), pages[i]) for i, start in enumerate(starts)]
            self.page_key = key
        return next((rows for start, end, rows in self.pages if start <= position < end), [])

    def sweep_glyph(self, canvas, font, font_key, char, x, y, progress, style):
        """Clip two identically rasterized glyphs; retain straight alpha and stroke."""
        key = (font_key, char, style.color, style.highlight, style.stroke, style.stroke_width)
        if key not in self.glyphs:
            box = font.getbbox(char, stroke_width=style.stroke_width)
            left, top, right, bottom = box
            size = (max(1, right - left), max(1, bottom - top))
            images = []
            for color in (style.color, style.highlight):
                image = Image.new('RGBA', size)
                ImageDraw.Draw(image).text((-left, -top), char, font=font, fill=color, stroke_width=style.stroke_width, stroke_fill=style.stroke)
                images.append(image)
            if len(self.glyphs) >= 512:
                self.glyphs.clear()
            self.glyphs[key] = (box, font.getbbox(char), *images)
        box, ink, base, highlighted = self.glyphs[key]
        glyph = base.copy()
        boundary = round(ink[0] - box[0] + (ink[2] - ink[0]) * progress)
        boundary = min(glyph.width, max(0, boundary))
        if boundary:
            glyph.paste(highlighted.crop((0, 0, boundary, glyph.height)), (0, 0))
        destination = (round(x) + box[0], round(y) + box[1])
        if canvas.mode == 'RGBA':
            canvas.alpha_composite(glyph, dest=destination)
        else:
            canvas.paste(glyph, destination, glyph)

    def render(self, size, background, cues, position, style, *, transparent=False):
        width, height = size
        canvas = Image.new('RGBA', size, (0, 0, 0, 0)) if transparent else Image.new('RGB', size, style.background)
        if background is not None and (not transparent):
            if getattr(self, 'fit_source', None) is not background or getattr(self, 'fit_size', None) != size:
                self.fit_source, self.fit_size = (background, size)
                self.fit_image = ImageOps.contain(background, size, Image.Resampling.LANCZOS)
            fit = self.fit_image
            canvas.paste(fit, ((width - fit.width) // 2, (height - fit.height) // 2))
        if not cues:
            return canvas
        key = (style.font or default_font(), style.size)
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(key[0], key[1]) if key[0] else ImageFont.load_default(size=style.size)
        font = self.fonts[key]
        lines = self.page_at(cues, position, font, key, width, height, style)
        draw = ImageDraw.Draw(canvas)
        line_height = math.ceil(style.size * 1.45)
        y = height - style.bottom - len(lines) * line_height
        for cue, line, indices in lines:
            x = (width - font.getlength(line)) / 2
            for index, char in zip(indices, line):
                progress = float(not cue.spans and cue.sing_start is not None and (position >= cue.sing_start))
                for start, end, left, right in cue.spans:
                    if left <= index < right:
                        fraction = float(position - cue.start >= end) if end <= start else min(1.0, max(0.0, (position - cue.start - start) / (end - start)))
                        progress = min(1.0, max(0.0, fraction * (right - left) - (index - left)))
                        break
                if 0 < progress < 1:
                    self.sweep_glyph(canvas, font, key, char, x, y, progress, style)
                else:
                    draw.text((round(x), round(y)), char, font=font, fill=style.highlight if progress else style.color, stroke_width=style.stroke_width, stroke_fill=style.stroke)
                x += font.getlength(char)
            y += line_height
        return canvas

class Background:
    """Own this object on one worker thread; do not share a decoder across threads."""

    def __init__(self, path):
        self.path = str(path) if path else ''
        self.image = None
        self.container = None
        self.duration = 0.0
        self.iterator = None
        self.current = self.pending = None
        self.previous_target = -1.0
        if not path:
            return
        if Path(path).suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff'):
            with Image.open(path) as image:
                self.image = ImageOps.exif_transpose(image).convert('RGB')
            return
        self.container = av.open(str(path))
        if not self.container.streams.video:
            self.container.close()
            raise ValueError('The input file has no video stream')
        self.stream = self.container.streams.video[0]
        self.stream.thread_type = 'AUTO'
        self.origin = float((self.stream.start_time or 0) * self.stream.time_base)
        self.duration = float(self.stream.duration * self.stream.time_base) if self.stream.duration else float(self.container.duration or 0) / av.time_base
        self.iterator = iter(self.container.decode(self.stream))

    def _next(self):
        while True:
            frame = next(self.iterator, None)
            if frame is None:
                return None
            if frame.pts is not None:
                return (float(frame.pts * frame.time_base) - self.origin, frame)

    def at(self, position):
        if self.image is not None:
            return self.image
        if self.container is None or position < 0 or (self.duration and position >= self.duration):
            return None
        if position < self.previous_target or position - self.previous_target > 1:
            self.container.seek(int((self.origin + position) / self.stream.time_base), stream=self.stream, backward=True, any_frame=False)
            self.iterator = iter(self.container.decode(self.stream))
            self.current = self.pending = None
        self.previous_target = position
        if self.pending is None:
            self.pending = self._next()
        while self.pending is not None and self.pending[0] <= position + 1e-06:
            self.current = self.pending
            self.pending = self._next()
        if self.current is None:
            return None
        if not hasattr(self, 'cached_frame') or self.cached_frame is not self.current[1]:
            self.cached_frame = self.current[1]
            self.cached_image = self.current[1].to_image()
        return self.cached_image

    def close(self):
        if self.container:
            self.container.close()

def input_audio(path):
    chunks = []
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise ValueError('The input video has no audio stream; select No audio or Current SD3 mix')
        stream = container.streams.audio[0]
        origin = float((container.streams.video[0].start_time or 0) * container.streams.video[0].time_base)
        resampler = av.AudioResampler(format='fltp', layout='stereo', rate=44100)
        for frame in container.decode(stream):
            for audio in resampler.resample(frame):
                if audio.pts is None:
                    raise ValueError('Input audio has no timestamps; audio/video synchronization cannot be guaranteed')
                chunks.append((round((float(audio.pts * audio.time_base) - origin) * 44100), audio.to_ndarray().T.copy()))
        for audio in resampler.resample(None):
            chunks.append((round((float(audio.pts * audio.time_base) - origin) * 44100), audio.to_ndarray().T.copy()))
    if not chunks:
        raise ValueError('The input video has no decodable audio')
    count = max(0, max((start + len(samples) for start, samples in chunks)))
    result = np.zeros((count, 2), dtype=np.float32)
    for start, samples in chunks:
        left = max(0, -start)
        if len(samples) > left:
            result[max(0, start):start + len(samples)] = samples[left:]
    return result

def export_video(path, *, source='', green=False, cues=(), style=None, duration=30, size=(1280, 720), fps=30, lyric_offset=0, video_offset=0, audio='none', song=None, variant=None, settings=None, cancel=None, progress=lambda value: None, output_format='mp4'):
    """Render video/images/solid background with optional video audio or SD3 PCM.

    ProRes 4444 renders straight-alpha text only, independent of any background.
    External MIDI is not synthesized. Destination must not exist.
    """
    if duration <= 0 or duration > 24 * 3600 or fps not in (24, 25, 30) or any((n < 64 or n % 2 for n in size)):
        raise ValueError('Duration must be greater than 0 and at most 24 hours; use 24/25/30 fps and even dimensions')
    destination = Path(path)
    if output_format not in ('mp4', 'prores4444'):
        raise ValueError('Unsupported output format')
    alpha = output_format == 'prores4444'
    extension = '.mov' if alpha else '.mp4'
    if destination.suffix.lower() != extension:
        raise ValueError(f'This output format requires the {extension} extension')
    if destination.exists():
        raise ValueError('The destination already exists; choose a new filename')
    temporary = destination.with_name('.' + destination.stem + '.' + uuid.uuid4().hex + '.rendering' + extension)
    cancel = cancel or threading.Event()
    style = style or Style()
    renderer = Renderer()
    background = None
    try:
        background = Background(source if not (green or alpha) else '')
        samples = None
        tracks = []
        if audio == 'video':
            if not source:
                raise ValueError('Select a video with an audio track')
            samples = input_audio(source)
        elif audio == 'sd3':
            from engine import selected_tracks
            if song is None or not song.pcm or variant is None or (settings is None):
                raise ValueError('Load the matching SD3 and apply playback settings first')
            tracks = selected_tracks(song, variant, settings.mode)
            if not tracks or any((t >= len(song.pcm) for t in tracks)):
                raise ValueError('The current playback mode has no SD3 audio to export')
        elif audio != 'none':
            raise ValueError('Unknown export audio source')
        with av.open(str(temporary), 'w', format='mov' if alpha else 'mp4') as output:
            video = output.add_stream('prores_ks' if alpha else 'libx264', rate=fps)
            video.width, video.height = size
            video.pix_fmt = 'yuva444p10le' if alpha else 'yuv420p'
            video.options = {'profile': '4444', 'alpha_bits': '16'} if alpha else {'crf': '20', 'preset': 'veryfast'}
            if alpha:
                video.codec_context.colorspace = 1
                video.codec_context.color_primaries = 1
                video.codec_context.color_trc = 1
                video.codec_context.color_range = 1
            sound = None
            if audio != 'none':
                sound = output.add_stream('aac', rate=44100)
                sound.layout = 'stereo'
                sound.bit_rate = 192000
            frame_count = math.ceil(duration * fps)
            audio_position = 0
            audio_end = round(duration * 44100)
            for index in range(frame_count):
                if cancel.is_set():
                    raise InterruptedError('Export cancelled')
                position = index / fps
                image = renderer.render(size, background.at(position - video_offset), cues, position - lyric_offset, style, transparent=alpha)
                frame = av.VideoFrame.from_ndarray(np.asarray(image), format='rgba') if alpha else av.VideoFrame.from_image(image)
                if alpha:
                    frame = frame.reformat(format='yuva444p10le', dst_colorspace='ITU709')
                    frame.colorspace = 1
                    frame.color_range = 1
                frame.pts = index
                frame.time_base = Fraction(1, fps)
                for packet in video.encode(frame):
                    output.mux(packet)
                until = min(audio_end, round((index + 1) * 44100 / fps))
                while sound is not None and audio_position < until:
                    count = min(1024, until - audio_position)
                    if samples is not None:
                        block = np.zeros((count, 2), dtype=np.float32)
                        start = audio_position - round(video_offset * 44100)
                        left, right = (max(0, -start), min(count, len(samples) - start))
                        if right > left:
                            block[left:right] = samples[start + left:start + right]
                    else:
                        from engine import mix_block
                        block = mix_block(song, variant, tracks, audio_position, count, settings)
                    audio_frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(block.T), format='fltp', layout='stereo')
                    audio_frame.sample_rate = 44100
                    audio_frame.pts = audio_position
                    audio_frame.time_base = Fraction(1, 44100)
                    for packet in sound.encode(audio_frame):
                        output.mux(packet)
                    audio_position += count
                if index % fps == 0:
                    progress((index + 1) / frame_count)
            for packet in video.encode():
                output.mux(packet)
            if sound:
                for packet in sound.encode():
                    output.mux(packet)
        if cancel.is_set():
            raise InterruptedError('Export cancelled')
        temporary.rename(destination)
        progress(1.0)
    finally:
        if background is not None:
            background.close()
        if temporary.exists():
            temporary.unlink()
export_mp4 = export_video
