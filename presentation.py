"""Video/still-image preview, green-screen lyrics, editable timing and MP4 export UI."""
from dataclasses import replace
from pathlib import Path
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox, simpledialog
import bootstrap
from PIL import Image, ImageTk, ImageColor, ImageFont
import lyrics
from media import Background, Renderer, Style, default_font, export_video
EXPORT_FORMATS = {'MP4 / H.264 (background or green screen)': 'mp4', 'MOV / ProRes 4444 (transparent alpha lyrics)': 'prores4444'}

class Preview:

    def __init__(self, owner, green):
        self.owner, self.green = (owner, green)
        self.closed = False
        self.jobs = queue.Queue(maxsize=1)
        self.results = queue.Queue(maxsize=1)
        self.window = tk.Toplevel(owner.app.root)
        self.window.title('Green-screen lyrics - F11 fullscreen / Esc exit fullscreen' if green else 'Video and lyrics - F11 fullscreen / Esc exit fullscreen')
        self.window.geometry('960x540')
        self.controls = ttk.Frame(self.window, padding=5)
        self.edit_button = ttk.Button(self.controls, text='Edit lyrics... F2', command=self.open_editor)
        self.edit_button.pack(side='left')
        ttk.Button(self.controls, text='Play', command=owner.play).pack(side='left', padx=4)
        ttk.Button(self.controls, text='Pause', command=owner.pause).pack(side='left')
        self.clock = ttk.Label(self.controls)
        self.clock.pack(side='right')
        if not green:
            self.controls.pack(side='bottom', fill='x')
        self.canvas = tk.Canvas(self.window, background='#00ff00' if green else '#000000', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.window.bind('<F11>', lambda e: self.window.attributes('-fullscreen', not self.window.attributes('-fullscreen')))
        self.window.bind('<Escape>', lambda e: self.window.attributes('-fullscreen', False))
        self.window.bind('<F2>', lambda e: self.open_editor())
        self.window.bind('<F10>', lambda e: self.toggle_controls())
        self.menu = tk.Menu(self.window, tearoff=False)
        self.menu.add_command(label='Edit lyrics... F2', command=self.open_editor)
        self.menu.add_command(label='Show/hide controls F10', command=self.toggle_controls)
        self.canvas.bind('<Button-3>', lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.worker = threading.Thread(target=self.run, daemon=True, name='Video preview')
        self.worker.start()
        self.key = None
        self.tick()

    def open_editor(self):
        return self.owner.open_timeline(live=True)

    def toggle_controls(self):
        if self.controls.winfo_manager():
            self.controls.pack_forget()
        else:
            self.controls.pack(side='bottom', fill='x', before=self.canvas)

    @staticmethod
    def latest(target, value):
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        target.put_nowait(value)

    def run(self):
        background = None
        renderer = Renderer()
        try:
            while True:
                job = self.jobs.get()
                if job is None:
                    break
                generation, path, position, size, cues, style, lo, vo = job
                try:
                    if background is None or background.path != path:
                        if background:
                            background.close()
                        background = None
                        background = Background(path)
                    image = renderer.render(size, background.at(position - vo), cues, position - lo, style)
                    self.latest(self.results, (generation, image, None))
                except Exception as ex:
                    self.latest(self.results, (generation, None, str(ex)))
        finally:
            if background:
                background.close()

    def tick(self):
        if self.closed:
            return
        owner = self.owner
        position = owner.position()
        self.clock.configure(text=f'{position:.3f} s')
        size = owner.size()
        path = '' if self.green else owner.source.get()
        key = (owner.generation, path, round(position * 30), size, max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height()))
        if key != self.key:
            self.key = key
            self.latest(self.jobs, (key, path, position, size, owner.output_cues(), replace(owner.style), owner.lyric_offset, owner.video_offset))
        try:
            generation, image, error = self.results.get_nowait()
            if generation[0:2] == self.key[0:2] and generation[3:] == self.key[3:] and (abs(generation[2] - self.key[2]) <= 10):
                if error:
                    owner.status.set('Preview failed: ' + error)
                else:
                    image.thumbnail((max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())), Image.Resampling.LANCZOS)
                    self.photo = ImageTk.PhotoImage(image)
                    self.canvas.configure(background=owner.style.background)
                    self.canvas.delete('all')
                    self.canvas.create_image(self.canvas.winfo_width() // 2, self.canvas.winfo_height() // 2, image=self.photo, anchor='center')
        except queue.Empty:
            pass
        self.after = self.window.after(33, self.tick)

    def close(self):
        if not self.closed:
            self.closed = True
            self.window.after_cancel(self.after)
            self.latest(self.jobs, None)
            self.window.destroy()
            self.worker.join(timeout=1)

class Presentation:

    def __init__(self, app):
        self.app = app
        self.window = None
        self.previews = []
        self.cues = []
        self.cues_revision = 0
        self.editors = []
        self.generation = 0
        self.style = Style(font=default_font())
        self.lyric_offset = self.video_offset = 0.0
        self.local_position = 0.0
        self.local_start = None
        self.export_thread = None
        self.cancel = threading.Event()
        self.events = queue.Queue()
        root = app.root
        self.source = tk.StringVar(root)
        self.font = tk.StringVar(root, value=self.style.font)
        self.font_size = tk.StringVar(root, value='54')
        self.stroke_width = tk.StringVar(root, value='3')
        self.bottom = tk.StringVar(root, value='50')
        self.page_lines = tk.StringVar(root, value='2')
        self.immediate_line_change = tk.BooleanVar(root, value=False)
        self.timing_enabled = tk.BooleanVar(root, value=False)
        self.fill_early = tk.BooleanVar(root, value=True)
        self.timing_vars = {name: tk.StringVar(root, value=str(getattr(self.style, name))) for name in ('advance_ms', 'hold_ms', 'fade_in_ms', 'fade_out_ms', 'max_advance_ms')}
        self.colors = {name: tk.StringVar(root, value=getattr(self.style, name)) for name in ('color', 'highlight', 'stroke', 'background')}
        self.lyric_ms = tk.StringVar(root, value='0')
        self.video_ms = tk.StringVar(root, value='0')
        self.resolution = tk.StringVar(root, value='1280x720')
        self.duration = tk.StringVar(root, value='30')
        self.fps = tk.StringVar(root, value='30')
        self.follow = tk.BooleanVar(root, value=True)
        self.enable_preview = tk.BooleanVar(root, value=True)
        self.enable_export = tk.BooleanVar(root, value=False)
        self.filter_numeric = tk.BooleanVar(root, value=False)
        self.green_export = tk.BooleanVar(root, value=False)
        self.output_format = tk.StringVar(root, value=next(iter(EXPORT_FORMATS)))
        self.audio = tk.StringVar(root, value='No audio')
        self.status = tk.StringVar(root, value='Preview follows the main player, or runs independently without a song. Input-video audio is available for export only.')
        self.progress = tk.DoubleVar(root)
        self.closed = False
        self.dragging = False
        root.after(100, self.poll)
        if app.song:
            self.on_song_loaded(app.song)

    def size(self):
        return tuple(map(int, self.resolution.get().split('x')))

    def position(self):
        if self.follow.get() and self.app.ready:
            return self.app.engine.position()
        if self.local_start is not None:
            try:
                duration = float(self.duration.get())
            except ValueError:
                duration = 30
            return min(duration, self.local_position + time.perf_counter() - self.local_start)
        return self.local_position

    def play(self):
        if self.follow.get() and self.app.ready:
            self.app.play()
        elif self.local_start is None or self.position() >= float(self.duration.get()):
            if self.position() >= float(self.duration.get()):
                self.local_position = 0
            self.local_start = time.perf_counter()

    def pause(self):
        if self.follow.get() and self.app.ready:
            self.app.engine.command('pause')
        else:
            self.local_position = self.position()
            self.local_start = None

    def seek(self, value):
        if self.follow.get() and self.app.ready:
            self.app.engine.command('seek', value)
        else:
            self.local_position = max(0, value)
            if self.local_start is not None:
                self.local_start = time.perf_counter()
        self.generation += 1

    def open(self):
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return
        win = self.window = tk.Toplevel(self.app.root)
        win.title('Video / Images / Lyrics / Export')
        win.geometry('1280x800')
        win.minsize(900, 720)
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text='Video / still background').grid(row=0, column=0, sticky='w')
        ttk.Entry(frame, textvariable=self.source).grid(row=0, column=1, sticky='ew', padx=6)
        ttk.Button(frame, text='Choose...', command=self.choose_source).grid(row=0, column=2)
        row = ttk.Frame(frame)
        row.grid(row=1, column=0, columnspan=3, sticky='ew', pady=10)
        for index, (label, command) in enumerate([('Import lyrics / timing', self.load_lyrics), ('Load lyrics from MI3', self.load_mi3), ('Text / timestamps', self.edit), ('Character timeline...', self.open_timeline), ('Export MI3 timing', self.template), ('Export lyrics / subtitles...', self.save_lyrics)]):
            ttk.Button(row, text=label, command=command).grid(row=index // 3, column=index % 3, sticky='ew', padx=3, pady=2)
        ttk.Checkbutton(row, text='Filter [4-digit codes]', variable=self.filter_numeric, command=self.filter_changed).grid(row=2, column=0, columnspan=3, sticky='w', padx=5)
        ttk.Label(frame, text='Font file').grid(row=2, column=0, sticky='w')
        ttk.Entry(frame, textvariable=self.font).grid(row=2, column=1, sticky='ew', padx=6)
        ttk.Button(frame, text='Choose font...', command=self.choose_font).grid(row=2, column=2)
        ttk.Button(frame, text='Visibility timing...', command=self.open_timing_style).grid(row=2, column=3, padx=(8, 0))
        row = ttk.Frame(frame)
        row.grid(row=3, column=0, columnspan=3, sticky='w', pady=8)
        for title, variable, low, high in [('Font size (px)', self.font_size, 8, 200), ('Stroke (px)', self.stroke_width, 0, 12), ('Bottom margin (px)', self.bottom, 0, 500), ('Lines per screen', self.page_lines, 1, 4)]:
            ttk.Label(row, text=title).pack(side='left', padx=(3, 6))
            ttk.Spinbox(row, from_=low, to=high, textvariable=variable, width=6).pack(side='left', padx=(0, 16))
        ttk.Checkbutton(row, text='Advance after each line', variable=self.immediate_line_change, command=self.apply).pack(side='left')
        row = ttk.Frame(frame)
        row.grid(row=4, column=0, columnspan=3, sticky='w', pady=6)
        for name, label in [('color', 'Text color'), ('highlight', 'Highlight'), ('stroke', 'Stroke color'), ('background', 'Background / key color')]:
            ttk.Button(row, text=label, command=lambda n=name: self.choose_color(n)).pack(side='left', padx=3)
            ttk.Entry(row, textvariable=self.colors[name], width=9).pack(side='left', padx=(0, 5))
        row = ttk.Frame(frame)
        row.grid(row=5, column=0, columnspan=3, sticky='w', pady=8)
        for label, variable in [('Lyric offset (ms)', self.lyric_ms), ('Video offset (ms)', self.video_ms)]:
            ttk.Label(row, text=label).pack(side='left', padx=4)
            ttk.Spinbox(row, from_=-60000, to=60000, textvariable=variable, width=8).pack(side='left', padx=(0, 16))
        ttk.Button(row, text='Apply style and offsets', command=self.apply).pack(side='left')
        box = ttk.LabelFrame(frame, text='Preview - does not export automatically', padding=8)
        box.grid(row=6, column=0, columnspan=3, sticky='ew', pady=8)
        row = ttk.Frame(box)
        row.pack(fill='x')
        ttk.Checkbutton(row, text='Enable preview', variable=self.enable_preview, command=self.preview_toggle).pack(side='left')
        ttk.Checkbutton(row, text='Follow main player clock', variable=self.follow, command=self.follow_changed).pack(side='left', padx=12)
        ttk.Button(row, text='Video / image preview', command=lambda: self.preview(False)).pack(side='left', padx=4)
        ttk.Button(row, text='Green-screen lyrics', command=lambda: self.preview(True)).pack(side='left', padx=4)
        row = ttk.Frame(box)
        row.pack(fill='x', pady=8)
        ttk.Button(row, text='Play / resume', command=self.play).pack(side='left')
        ttk.Button(row, text='Pause', command=self.pause).pack(side='left', padx=5)
        ttk.Button(row, text='Back to start', command=lambda: self.seek(0)).pack(side='left')
        self.time_label = ttk.Label(row)
        self.time_label.pack(side='right')
        self.slider = ttk.Scale(box, from_=0, to=max(1, float(self.duration.get())))
        self.slider.pack(fill='x')
        self.slider.bind('<ButtonPress-1>', lambda event: setattr(self, 'dragging', True))
        self.slider.bind('<ButtonRelease-1>', self.seek_slider)
        self.slider.bind('<KeyRelease>', self.seek_slider)
        output = ttk.LabelFrame(frame, text='Export video - a still image can fill the entire background', padding=8)
        output.grid(row=7, column=0, columnspan=3, sticky='ew', pady=8)
        row = ttk.Frame(output)
        row.pack(fill='x')
        ttk.Checkbutton(row, text='Enable export (off = preview only)', variable=self.enable_export, command=self.export_toggle).pack(side='left')
        self.green_checkbox = ttk.Checkbutton(row, text='Export solid / green-screen lyrics', variable=self.green_export)
        self.green_checkbox.pack(side='left', padx=12)
        row = ttk.Frame(output)
        row.pack(fill='x', pady=(6, 0))
        ttk.Label(row, text='Output format').pack(side='left', padx=4)
        self.format_box = ttk.Combobox(row, textvariable=self.output_format, values=list(EXPORT_FORMATS), state='readonly', width=42)
        self.format_box.pack(side='left')
        self.format_box.bind('<<ComboboxSelected>>', self.format_changed)
        ttk.Label(row, text='Transparent MOV exports lyrics only; background alpha is 0').pack(side='left', padx=10)
        row = ttk.Frame(output)
        row.pack(fill='x', pady=8)
        for label, variable, values in [('Resolution', self.resolution, ('640x360', '1280x720', '1920x1080')), ('Frame rate', self.fps, ('24', '25', '30')), ('Audio', self.audio, ('No audio', 'Input video audio', 'Current audio mix'))]:
            ttk.Label(row, text=label).pack(side='left', padx=4)
            ttk.Combobox(row, textvariable=variable, values=values, state='readonly', width=14 if label == 'Audio' else 11).pack(side='left')
        ttk.Label(row, text='Duration (s)').pack(side='left', padx=(12, 4))
        ttk.Entry(row, textvariable=self.duration, width=8).pack(side='left')
        row = ttk.Frame(output)
        row.pack(fill='x')
        self.export_button = ttk.Button(row, text='Export MP4...', command=self.export, state='disabled')
        self.export_button.pack(side='left')
        self.cancel_button = ttk.Button(row, text='Cancel export', command=self.cancel.set, state='disabled')
        self.cancel_button.pack(side='left', padx=8)
        ttk.Progressbar(row, variable=self.progress, maximum=1).pack(side='left', fill='x', expand=True)
        ttk.Label(frame, text='External MIDI audio is not recorded in exports. MI3 character templates are estimates; edit them in the timeline. JSON / CSV retain character start/end times.', wraplength=840).grid(row=8, column=0, columnspan=3, sticky='w', pady=6)
        ttk.Label(frame, textvariable=self.status, wraplength=840).grid(row=9, column=0, columnspan=3, sticky='w')
        self.format_changed()

    def choose_color(self, name):
        chosen = colorchooser.askcolor(self.colors[name].get(), parent=self.window)[1]
        if chosen:
            self.colors[name].set(chosen)
            self.apply()

    def seek_slider(self, event=None):
        self.dragging = False
        self.seek(float(self.slider.get()))

    def follow_changed(self):
        if not self.follow.get():
            self.local_position = self.app.engine.position()
            self.local_start = None
        self.generation += 1

    def choose_font(self):
        path = filedialog.askopenfilename(parent=self.window, filetypes=[('Fonts', '*.ttf *.ttc *.otf'), ('All files', '*.*')])
        if path:
            self.font.set(path)
            self.apply()

    def apply(self):
        try:
            style = Style(font=self.font.get(), size=int(self.font_size.get()), stroke_width=int(self.stroke_width.get()), bottom=int(self.bottom.get()), page_lines=int(self.page_lines.get()), immediate_line_change=self.immediate_line_change.get(), timing_enabled=self.timing_enabled.get(), fill_early=self.fill_early.get(), **{name: int(value.get()) for name, value in self.timing_vars.items()}, **{key: value.get() for key, value in self.colors.items()})
            if any((not 0 <= getattr(style, name) <= 60000 for name in self.timing_vars)):
                raise ValueError('Visibility timing values must be integers from 0 to 60000 ms')
            if style.timing_enabled and style.fill_early and (style.max_advance_ms < style.advance_ms):
                raise ValueError('Maximum lead must not be less than the normal lead time')
            if not 8 <= style.size <= 200 or not 0 <= style.stroke_width <= 12 or (not 0 <= style.bottom <= 500) or (not 1 <= style.page_lines <= 4):
                raise ValueError('Font size: 8-200; stroke: 0-12; bottom margin: 0-500; lines per screen: 1-4')
            for value in self.colors.values():
                ImageColor.getrgb(value.get())
            if style.font:
                ImageFont.truetype(style.font, style.size)
            lo, vo = (float(self.lyric_ms.get()) / 1000, float(self.video_ms.get()) / 1000)
            if not all((-60 <= x <= 60 for x in (lo, vo))):
                raise ValueError('Offsets must be within +/-60000 ms')
            self.style, self.lyric_offset, self.video_offset = (style, lo, vo)
            self.generation += 1
            return True
        except Exception as ex:
            messagebox.showerror('Invalid settings', str(ex), parent=self.window)
            return False

    def open_timing_style(self):
        from timing_style import TimingStyleDialog
        TimingStyleDialog(self)

    def choose_source(self):
        path = filedialog.askopenfilename(parent=self.window, filetypes=[('Video or image', '*.mp4 *.mkv *.mov *.avi *.ts *.webm *.png *.jpg *.jpeg *.bmp *.webp'), ('All files', '*.*')])
        if path:
            try:
                background = Background(path)
                if background.duration:
                    self.duration.set(f'{max(background.duration, self.app.engine.duration if self.app.ready else 0):.3f}')
                background.close()
                self.source.set(path)
                self.generation += 1
            except Exception as ex:
                messagebox.showerror('Background load failed', str(ex), parent=self.window)

    def output_cues(self):
        return lyrics.output_cues(self.cues, self.filter_numeric.get())

    def filter_changed(self):
        self.generation += 1
        self.status.set('Filter enabled: preview and exports hide [0000]-[9999]; the editor keeps the original text.' if self.filter_numeric.get() else 'Filter disabled: preview and exports retain the original lyric text.')

    def open_timeline(self, live=False):
        from timeline import TimelineEditor
        if live:
            existing = next((editor for editor in self.editors if editor.live and (not editor.closed) and (editor.revision == self.cues_revision)), None)
            if existing:
                existing.window.deiconify()
                existing.window.lift()
                existing.window.focus_set()
                return existing
        editor = TimelineEditor(self, live=live)
        self.editors.append(editor)
        if live:
            editor.select_current()
            editor.window.focus_set()
        return editor

    def set_cues(self, cues, source):
        self.cues = cues
        self.cues_revision += 1
        self.generation += 1
        if not self.app.song and cues:
            self.duration.set(f'{max((c.end for c in cues)) + 1:.2f}')
        self.status.set(f'{source}：{len(cues)} lyric lines; positive offsets delay the lyrics.')

    def on_song_loaded(self, song):
        self.cues = []
        self.cues_revision += 1
        self.generation += 1
        self.local_position, self.local_start = (0, None)
        variant = song.variants[max(0, self.app.variant_box.current())]
        self.duration.set(f'{max([variant.duration] + [len(p) / 44100 for p in song.pcm]):.3f}')
        if self.app.ready and getattr(self.app.engine, 'song', None) is song:
            self.duration.set(f'{self.app.engine.duration:.3f}')
        self.audio.set('Current audio mix' if song.pcm else 'No audio')
        try:
            if song.mi3 and song.mi3.suffix.lower() == '.mi3':
                self.set_cues(lyrics.mi3_cues(song.mi3), 'MI3 firmware-clock character template (estimated; editable)')
            elif getattr(song, 'lyric_cues', []):
                self.set_cues(song.lyric_cues, 'MIDI / XF: ' + song.lyric_source)
            else:
                for suffix in ('.lrc', '.srt', '.vtt', '.ass', '.ssa', '.ttml', '.dfxp', '.scc', '.xf'):
                    sidecar = (song.mi3 or song.sd3).with_suffix(suffix)
                    if sidecar.exists():
                        self.set_cues(lyrics.load(sidecar), sidecar.name)
                        break
        except Exception as ex:
            self.status.set(f'MI3 lyrics unavailable: {ex}; you can import external LRC/ASS lyrics.')

    def load_lyrics(self):
        from subtitle_formats import IMPORT_PATTERN
        path = filedialog.askopenfilename(parent=self.window, filetypes=[('Timed lyrics', IMPORT_PATTERN), ('All files', '*.*')])
        if path:
            try:
                self.set_cues(lyrics.load(path), Path(path).name)
            except Exception as ex:
                messagebox.showerror('Lyric load failed', str(ex), parent=self.window)

    def save_lyrics(self):
        from subtitle_formats import EXPORT_TYPES
        path = filedialog.asksaveasfilename(parent=self.window, defaultextension='.json', filetypes=EXPORT_TYPES)
        if path:
            try:
                lyrics.protect_source(path, self.app.song)
                lyrics.save_cues(path, self.cues, self.filter_numeric.get())
                self.status.set('Lyrics exported: ' + path + '; target formats may quantize or simplify word timing; save JSON/CSV for a complete editable timeline.')
            except Exception as ex:
                messagebox.showerror('Lyric export failed', str(ex), parent=self.window)

    def mi3_selection(self):
        path = str(self.app.song.mi3) if self.app.song and self.app.song.mi3 and (self.app.song.mi3.suffix.lower() == '.mi3') else ''
        if not path:
            path = filedialog.askopenfilename(parent=self.window, filetypes=[('MI3', '*.MI3')])
        if not path:
            return None
        resource = simpledialog.askinteger('Lyric resource', 'SNG resource index (starts at 0; normally select 0):', initialvalue=0, minvalue=0, parent=self.window)
        return (path, resource) if resource is not None else None

    def load_mi3(self):
        selected = self.mi3_selection()
        if selected:
            try:
                self.set_cues(lyrics.mi3_cues(*selected), 'MI3 firmware-clock character template (estimated; editable)')
            except Exception as ex:
                messagebox.showerror('MI3 lyric load failed', str(ex), parent=self.window)

    def template(self):
        selected = self.mi3_selection()
        if not selected:
            return
        folder = filedialog.askdirectory(parent=self.window, title='Select timing-template output folder')
        if folder:
            try:
                files = lyrics.export_template(selected[0], folder, selected[1], self.filter_numeric.get())
                self.status.set('Exported JSON / CSV / LRC / ASS: ' + str(files[0].parent))
            except Exception as ex:
                messagebox.showerror('Template export failed', str(ex), parent=self.window)

    def edit(self):
        win = tk.Toplevel(self.app.root)
        win.title('Lyric text timing - Press F8 during playback to timestamp the current line')
        win.geometry('850x600')
        editor = tk.Text(win, wrap='word', font=('Segoe UI', 12), undo=True)
        editor.pack(fill='both', expand=True, padx=10, pady=10)
        editor.insert('1.0', '\n'.join((lyrics.stamp(c.sing_start if c.sing_start is not None else c.start) + c.text for c in self.cues)))

        def mark(event=None):
            line = editor.index('insert').split('.')[0]
            text = editor.get(line + '.0', line + '.end')
            text = re.sub('^(?:\\[\\d+:\\d+(?:\\.\\d+)?\\])+', '', text)
            editor.delete(line + '.0', line + '.end')
            editor.insert(line + '.0', lyrics.stamp(self.position() - self.lyric_offset) + text)
            editor.mark_set('insert', f'{int(line) + 1}.0')
            editor.see('insert')

        def parsed():
            text = editor.get('1.0', 'end').strip()
            for index, line in enumerate(text.splitlines()):
                if line.strip() and (not re.match('^\\[', line)):
                    raise ValueError(f'Item {index + 1} has no timestamp; add a time tag')
            return (text, lyrics.lrc(text))

        def use():
            try:
                _, cues = parsed()
                self.set_cues(cues, 'Edited lyrics')
            except Exception as ex:
                messagebox.showerror('Invalid lyric timing', str(ex), parent=win)

        def save():
            try:
                text, _ = parsed()
                path = filedialog.asksaveasfilename(parent=win, defaultextension='.lrc', filetypes=[('LRC', '*.lrc')])
                if path:
                    Path(path).write_text((lyrics.clean_text(text) if self.filter_numeric.get() else text) + '\n', encoding='utf-8')
            except Exception as ex:
                messagebox.showerror('Save failed', str(ex), parent=win)
        row = ttk.Frame(win, padding=8)
        row.pack(fill='x')
        for label, command in [('Timestamp line (F8)', mark), ('Apply to preview', use), ('Save LRC...', save)]:
            ttk.Button(row, text=label, command=command).pack(side='left', padx=4)
        win.bind('<F8>', mark)

    def preview(self, green):
        if not self.enable_preview.get():
            self.status.set('Preview is disabled; select Enable preview before opening a window.')
            return
        if self.apply():
            for preview in self.previews:
                if not preview.closed and preview.green == green:
                    preview.window.lift()
                    return
            self.previews.append(Preview(self, green))

    def preview_toggle(self):
        if not self.enable_preview.get():
            for preview in self.previews:
                preview.close()
            self.previews.clear()

    def export_toggle(self):
        if hasattr(self, 'export_button') and self.export_button.winfo_exists():
            running = self.export_thread is not None and self.export_thread.is_alive()
            self.export_button.configure(state='normal' if self.enable_export.get() and (not running) else 'disabled')
            self.cancel_button.configure(state='normal' if running else 'disabled')

    def format_changed(self, event=None):
        alpha = EXPORT_FORMATS[self.output_format.get()] == 'prores4444'
        self.green_checkbox.configure(state='disabled' if alpha else 'normal')
        self.export_button.configure(text='Export transparent MOV...' if alpha else 'Export MP4...')
        self.export_toggle()

    def export(self):
        if not self.enable_export.get() or (self.export_thread and self.export_thread.is_alive()) or (not self.apply()):
            return
        try:
            if self.app.song and (not self.app.ready):
                raise ValueError('Apply playback settings and wait until ready before exporting')
            duration = float(self.duration.get())
            fps = int(self.fps.get())
            if not 0 < duration <= 86400:
                raise ValueError('Export duration must be greater than 0 and at most 24 hours')
            output_format = EXPORT_FORMATS[self.output_format.get()]
            extension = '.mov' if output_format == 'prores4444' else '.mp4'
            path = filedialog.asksaveasfilename(parent=self.window, defaultextension=extension, filetypes=[('QuickTime / ProRes 4444', '*.mov')] if extension == '.mov' else [('MP4', '*.mp4')])
            if not path:
                return
            if Path(path).exists():
                raise ValueError('Choose a new filename; existing videos are not overwritten')
            if Path(path).suffix.lower() != extension:
                raise ValueError(f'For this format, use the {extension} extension')
            engine = self.app.engine
            settings = replace(engine.settings, gains=list(engine.settings.gains))
            kwargs = dict(source=self.source.get(), green=self.green_export.get(), cues=self.output_cues(), style=replace(self.style), duration=duration, size=self.size(), fps=fps, lyric_offset=self.lyric_offset, video_offset=self.video_offset, audio={'No audio': 'none', 'Input video audio': 'video', 'Current audio mix': 'sd3'}[self.audio.get()], song=engine.song, variant=engine.variant, settings=settings, output_format=output_format)
        except Exception as ex:
            messagebox.showerror('Invalid export settings', str(ex), parent=self.window)
            return
        self.cancel.clear()
        self.progress.set(0)

        def work():
            try:
                export_video(path, **kwargs, cancel=self.cancel, progress=lambda value: self.events.put(('progress', value)))
                self.events.put(('done', path))
            except InterruptedError:
                self.events.put(('cancelled', 'Export cancelled; the incomplete file was removed'))
            except Exception as ex:
                self.events.put(('error', str(ex)))
        self.export_thread = threading.Thread(target=work, daemon=True, name='Video export')
        self.export_thread.start()
        self.export_toggle()
        self.status.set('Exporting in the background; preview and export use independent video decoders.')

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'progress':
                    self.progress.set(value)
                else:
                    self.status.set('Exported: ' + value if kind == 'done' else str(value))
        except queue.Empty:
            pass
        if self.window and self.window.winfo_exists():
            self.export_toggle()
            if hasattr(self, 'time_label'):
                position = self.position()
                self.time_label.configure(text=f'{position:.2f} s')
                try:
                    self.slider.configure(to=max(1, float(self.duration.get())))
                    if not getattr(self, 'dragging', False):
                        self.slider.set(position)
                    if self.local_start is not None and position >= float(self.duration.get()):
                        self.local_position, self.local_start = (position, None)
                except ValueError:
                    pass
        self.app.root.after(100, self.poll)

    def close(self):
        self.closed = True
        self.cancel.set()
        for editor in self.editors:
            editor.close()
        for preview in self.previews:
            preview.close()
        if self.export_thread:
            self.export_thread.join(timeout=5)
