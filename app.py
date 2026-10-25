"""Minimal MI3 + SD3 synchronized desktop player."""
import argparse
import logging
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
logging.basicConfig(filename=Path(__file__).with_name('player.log'), level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', encoding='utf8')
try:
    import bootstrap
    import sounddevice as sd
    from engine import PlayerEngine, Settings
    from midi_out import devices as midi_devices
    from song import load_song, RATE
except Exception as ex:
    logging.exception('Startup failed')
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror('Missing player dependencies', f'{ex}\n\nExtract the entire portable ZIP and run start_player.cmd.\nFor source development, install the packages in requirements.txt.')
    root.destroy()
    raise SystemExit(1)
MODES = {'Auto: MDT-linked audio': 'auto', 'Manual: all audio + MIDI': 'mix', 'Audio only': 'audio', 'MIDI only': 'midi'}

def stamp(seconds):
    minutes, rest = divmod(max(0, seconds), 60)
    return f'{int(minutes):02d}:{rest:05.2f}'

class App:

    def __init__(self, root, mi3='', sd3='', engine=None):
        self.root = root
        self.engine = engine or PlayerEngine()
        self.song = None
        self.loading = False
        self.ready = False
        self.updating = False
        self.dragging = False
        self.closed = False
        self.load_generation = 0
        self.events = queue.Queue()
        self.route_maps = {}
        self.route_index = None
        self.presentation = None
        root.title('MI3 + SD3 Sync Player - Openjs-wx 0.7 English')
        root.geometry('1080x990')
        root.minsize(900, 850)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10))
        style.configure('Title.TLabel', font=('Segoe UI', 20, 'bold'))
        outer = ttk.Frame(root, padding=18)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='MI3 + SD3 Sync Player', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='MI3 / multiple SMF files - Per-track routing to four MIDI ports - Synchronized SD3 audio').pack(anchor='w', pady=(3, 12))
        files = ttk.LabelFrame(outer, text='Song files', padding=10)
        files.pack(fill='x')
        files.columnconfigure(1, weight=1)
        self.mi3_path = tk.StringVar(value=mi3)
        self.sd3_path = tk.StringVar(value=sd3)
        for row, (label, variable, extension) in enumerate([('MI3', self.mi3_path, '.MI3'), ('SD3', self.sd3_path, '.SD3')]):
            ttk.Label(files, text=label, width=5).grid(row=row, column=0, sticky='w', pady=3)
            ttk.Entry(files, textvariable=variable).grid(row=row, column=1, sticky='ew', padx=6)
            ttk.Button(files, text='Browse...', command=lambda v=variable, e=extension: self.browse(v, e)).grid(row=row, column=2)
        ttk.Button(files, text='Load files', command=self.load).grid(row=0, column=3, rowspan=2, padx=(10, 0), sticky='ns')
        ttk.Button(files, text='Load SMF files...', command=self.load_smf).grid(row=0, column=4, rowspan=2, padx=(8, 0), sticky='ns')
        settings = ttk.LabelFrame(outer, text='Playback and synchronization', padding=10)
        settings.pack(fill='x', pady=10)
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)
        self.variant_var = tk.StringVar()
        self.variant_box = ttk.Combobox(settings, textvariable=self.variant_var, state='readonly')
        self.variant_box.grid(row=0, column=1, columnspan=3, sticky='ew', pady=4)
        ttk.Label(settings, text='Music resource').grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.variant_box.bind('<<ComboboxSelected>>', self.settings_changed)
        self.mode_var = tk.StringVar(value=next(iter(MODES)))
        ttk.Label(settings, text='Playback mode').grid(row=1, column=0, sticky='w')
        self.mode_box = ttk.Combobox(settings, textvariable=self.mode_var, values=list(MODES), state='readonly')
        self.mode_box.grid(row=1, column=1, sticky='ew', padx=(0, 15), pady=4)
        self.mode_box.bind('<<ComboboxSelected>>', self.settings_changed)
        self.offset_audio = tk.StringVar(value='0')
        self.offset_midi = tk.StringVar(value='0')
        ttk.Label(settings, text='Audio offset (ms)').grid(row=1, column=2, sticky='w')
        ttk.Spinbox(settings, from_=-10000, to=10000, increment=10, textvariable=self.offset_audio, width=10).grid(row=1, column=3, sticky='w')
        ttk.Label(settings, text='MIDI offset (ms)').grid(row=2, column=2, sticky='w')
        ttk.Spinbox(settings, from_=-10000, to=10000, increment=10, textvariable=self.offset_midi, width=10).grid(row=2, column=3, sticky='w')
        ttk.Label(settings, text='Audio output').grid(row=2, column=0, sticky='w')
        self.audio_var = tk.StringVar()
        self.audio_box = ttk.Combobox(settings, textvariable=self.audio_var, state='readonly')
        self.audio_box.grid(row=2, column=1, sticky='ew', padx=(0, 15), pady=4)
        self.midi_vars = [tk.StringVar() for _ in range(4)]
        self.midi_source_vars = [tk.StringVar(value='Source A' if p % 2 == 0 else 'Source B') for p in range(4)]
        self.midi_boxes = []
        for port in range(4):
            row, column = (3 + port % 2, 0 if port < 2 else 2)
            ttk.Label(settings, text=f"MIDI port {'ABCD'[port]}").grid(row=row, column=column, sticky='w')
            group = ttk.Frame(settings)
            group.grid(row=row, column=column + 1, sticky='ew', padx=(0, 15), pady=4)
            box = ttk.Combobox(group, textvariable=self.midi_vars[port], state='readonly', width=22)
            box.pack(side='left', fill='x', expand=True)
            ttk.Combobox(group, textvariable=self.midi_source_vars[port], values=['Source A', 'Source B'], state='readonly', width=5).pack(side='left', padx=(5, 0))
            self.midi_boxes.append(box)
        ttk.Button(settings, text='Refresh devices', command=self.refresh_devices).grid(row=5, column=0, sticky='w')
        ttk.Button(settings, text='Apply settings (restart)', command=self.apply).grid(row=5, column=1, columnspan=3, sticky='w')
        ttk.Label(settings, text='Positive offsets delay playback. Source A/B define default routing; the track table controls actual outputs.').grid(row=6, column=0, columnspan=4, sticky='w', pady=(5, 0))
        routing = ttk.LabelFrame(outer, text='MIDI track routing: click A/B/C/D to toggle; select multiple outputs or disable all to mute', padding=6)
        routing.pack(fill='x', pady=(0, 6))
        table_frame = ttk.Frame(routing)
        table_frame.pack(fill='x')
        self.route_tree = ttk.Treeview(table_frame, columns=('name', 'channel', 'events', 'A', 'B', 'C', 'D'), show='headings', height=6, selectmode='extended')
        for col, title, width in [('name', 'Track / file', 430), ('channel', 'Channels', 90), ('events', 'Notes / events', 100), *[(p, p, 48) for p in 'ABCD']]:
            self.route_tree.heading(col, text=title)
            self.route_tree.column(col, width=width, minwidth=35, stretch=col == 'name', anchor='w' if col == 'name' else 'center')
        self.route_tree.pack(side='left', fill='x', expand=True)
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.route_tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.route_tree.configure(yscrollcommand=scrollbar.set)
        self.route_tree.bind('<Button-1>', self.toggle_route)
        row = ttk.Frame(routing)
        row.pack(fill='x', pady=(4, 0))
        for port in range(4):
            ttk.Button(row, text=f"Selected tracks -> {'ABCD'[port]}", command=lambda p=port: self.assign_routes((p,))).pack(side='left', padx=2)
        ttk.Button(row, text='Mute selected', command=lambda: self.assign_routes(())).pack(side='left', padx=2)
        ttk.Button(row, text='Use default sources', command=self.default_routes).pack(side='left', padx=2)
        ttk.Label(row, text='Click Apply settings after changes').pack(side='right')
        transport = ttk.Frame(outer)
        transport.pack(fill='x', pady=4)
        self.play_button = ttk.Button(transport, text='Play', command=self.play, state='disabled')
        self.play_button.pack(side='left')
        ttk.Button(transport, text='Pause', command=lambda: self.engine.command('pause')).pack(side='left', padx=6)
        ttk.Button(transport, text='Stop', command=lambda: self.engine.command('stop')).pack(side='left')
        ttk.Button(transport, text='Video / Lyrics / Export...', command=self.open_presentation).pack(side='left', padx=10)
        self.time_var = tk.StringVar(value='00:00.00 / 00:00.00')
        ttk.Label(transport, textvariable=self.time_var).pack(side='right')
        self.timeline = ttk.Scale(outer, from_=0, to=1, orient='horizontal')
        self.timeline.pack(fill='x', pady=5)
        self.timeline.bind('<ButtonPress-1>', lambda event: setattr(self, 'dragging', True))
        self.timeline.bind('<ButtonRelease-1>', self.seek)
        self.timeline.bind('<KeyRelease>', self.seek)
        self.mix_frame = ttk.LabelFrame(outer, text='Audio mix (live controls)', padding=8)
        self.mix_frame.pack(fill='x', pady=5)
        self.gain_vars = []
        self.master_var = tk.DoubleVar(value=75)
        ttk.Label(self.mix_frame, text='Audio master volume').grid(row=0, column=0, sticky='w')
        ttk.Scale(self.mix_frame, from_=0, to=100, variable=self.master_var, command=self.change_mix).grid(row=0, column=1, sticky='ew', padx=10)
        self.mix_frame.columnconfigure(1, weight=1)
        self.track_widgets = []
        self.status = tk.StringVar(value='Select an MI3 file. A matching SD3 in the same folder is selected automatically. Loading does not start playback.')
        ttk.Label(outer, textvariable=self.status, wraplength=940).pack(anchor='w', pady=5)
        self.log = tk.Text(outer, height=7, font=('Consolas', 10), wrap='word', state='disabled')
        self.log.pack(fill='both', expand=True, pady=(3, 0))
        self.refresh_devices()
        root.after(80, self.poll)

    def write(self, text):
        logging.info(text)
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 180:
            self.log.delete('1.0', '40.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def open_presentation(self):
        if self.presentation is None:
            from presentation import Presentation
            self.presentation = Presentation(self)
        self.presentation.open()

    def browse(self, variable, extension):
        path = filedialog.askopenfilename(filetypes=[(extension[1:] + ' files', '*' + extension), ('All files', '*.*')])
        if path:
            variable.set(path)
            if extension == '.MI3':
                candidate = Path(path).with_suffix('.SD3')
                self.sd3_path.set(str(candidate) if candidate.exists() else '')

    def refresh_devices(self):
        old_audio = self.audio_var.get()
        self.audio_lookup = {'System default output': None}
        try:
            for index, dev in enumerate(sd.query_devices()):
                if dev['max_output_channels'] >= 2:
                    self.audio_lookup[f"{index}: {dev['name']}"] = index
            self.midi_lookup = {'Do not send MIDI': None}
            for index, name in midi_devices():
                self.midi_lookup[f'{index}: {name}'] = index
            self.audio_box['values'] = list(self.audio_lookup)
            self.audio_var.set(old_audio if old_audio in self.audio_lookup else 'System default output')
            for index, box in enumerate(self.midi_boxes):
                old = self.midi_vars[index].get()
                box['values'] = list(self.midi_lookup)
                default = list(self.midi_lookup)[1] if index == 0 and len(self.midi_lookup) > 1 else 'Do not send MIDI'
                self.midi_vars[index].set(old if old in self.midi_lookup else default)
        except Exception as ex:
            self.midi_lookup = {'Do not send MIDI': None}
            self.audio_box['values'] = list(self.audio_lookup)
            self.audio_var.set('System default output')
            for box, variable in zip(self.midi_boxes, self.midi_vars):
                box['values'] = list(self.midi_lookup)
                variable.set('Do not send MIDI')
            self.write(f'Device enumeration failed: {ex}')

    def load(self):
        if self.loading:
            return
        path = self.mi3_path.get().strip()
        if not path:
            messagebox.showinfo('Select file', 'Select an MI3 file')
            return
        self.engine.command('stop')
        self.ready = False
        self.play_button.configure(state='disabled')
        self.loading = True
        self.load_generation += 1
        generation = self.load_generation
        sd3 = self.sd3_path.get().strip() or None
        self.status.set('Loading...')

        def work():
            try:
                result = load_song(path, sd3, lambda text: self.events.put(('progress', generation, text)))
                self.events.put(('loaded', generation, result))
            except Exception as ex:
                logging.exception('Load failed')
                self.events.put(('load_error', generation, str(ex)))
        threading.Thread(target=work, daemon=True, name='Song loader').start()

    def load_smf(self):
        if self.loading:
            return
        paths = filedialog.askopenfilenames(title='Select one or more SMF files (play together)', filetypes=[('Standard MIDI files', '*.mid *.midi'), ('All files', '*.*')])
        if not paths:
            return
        self.engine.command('stop')
        self.ready = False
        self.play_button.configure(state='disabled')
        self.loading = True
        self.load_generation += 1
        generation = self.load_generation
        self.status.set('Loading SMF...')

        def work():
            try:
                from smf import load_smf_song
                song = load_smf_song(paths, lambda text: self.events.put(('progress', generation, text)))
                self.events.put(('loaded', generation, song))
            except Exception as ex:
                logging.exception('SMF load failed')
                self.events.put(('load_error', generation, str(ex)))
        threading.Thread(target=work, daemon=True, name='SMF loader').start()

    def render_routes(self):
        if self.route_index is None:
            return
        self.route_tree.delete(*self.route_tree.get_children())
        variant = self.song.variants[self.route_index]
        routes = self.route_maps[self.route_index]
        for part in variant.parts:
            self.route_tree.insert('', 'end', iid=str(part.id), values=(part.name, part.channels, f'{part.note_count} / {part.event_count}', *['✓' if p in routes[part.id] else '·' for p in range(4)]))

    def ensure_routes(self):
        if self.song is None:
            return
        index = max(0, self.variant_box.current())
        if index not in self.route_maps:
            self.route_maps[index] = {part.id: set(range(4)) if part.shared else {p for p, v in enumerate(self.midi_source_vars) if (0 if v.get() == 'Source A' else 1) == part.source_port} if part.source_port < 2 else {part.source_port % 4} for part in self.song.variants[index].parts}
        if self.route_index != index:
            self.route_index = index
            self.render_routes()

    def toggle_route(self, event):
        if self.route_tree.identify_region(event.x, event.y) != 'cell':
            return
        row = self.route_tree.identify_row(event.y)
        column = self.route_tree.identify_column(event.x)
        if row and column in ('#4', '#5', '#6', '#7'):
            ports = self.route_maps[self.route_index][int(row)]
            port = int(column[1:]) - 4
            ports.symmetric_difference_update({port})
            self.route_tree.set(row, 'ABCD'[port], '✓' if port in ports else '·')
            return 'break'

    def assign_routes(self, ports):
        if self.route_index is None:
            return
        for row in self.route_tree.selection():
            self.route_maps[self.route_index][int(row)] = set(ports)
            for port in range(4):
                self.route_tree.set(row, 'ABCD'[port], '✓' if port in ports else '·')

    def default_routes(self):
        if self.song is None:
            return
        index = max(0, self.variant_box.current())
        self.route_maps.pop(index, None)
        self.route_index = None
        self.ensure_routes()

    def on_loaded(self, song):
        self.loading = False
        self.song = song
        self.route_maps = {}
        self.route_index = None
        values = [f"{v.label} {v.index} - Audio {v.selected or 'None'} · {len(v.parts)} tracks - {v.note_count} notes" for v in song.variants]
        self.variant_box['values'] = values
        default_index = 0
        if not song.pcm:
            default_index = next((i for i, v in enumerate(song.variants) if not v.selected), 0)
        self.variant_box.current(default_index)
        self.ensure_routes()
        if song.variants[default_index].label == 'SMF':
            self.mode_var.set('MIDI only')
            self.mi3_path.set('')
            self.sd3_path.set('')
        elif self.mode_var.get() == 'Audio only' and (not song.pcm):
            self.mode_var.set(next(iter(MODES)))
        for widget in self.track_widgets:
            widget.destroy()
        self.track_widgets.clear()
        self.gain_vars = []
        for index, pcm in enumerate(song.pcm):
            gain = tk.DoubleVar(value=70)
            self.gain_vars.append(gain)
            label = ttk.Label(self.mix_frame, text=f'SD3 {index} · {len(pcm) / RATE:.2f}s')
            label.grid(row=index + 1, column=0, sticky='w')
            slider = ttk.Scale(self.mix_frame, from_=0, to=100, variable=gain, command=self.change_mix)
            slider.grid(row=index + 1, column=1, sticky='ew', padx=10)
            self.track_widgets.extend((label, slider))
        self.write(f'Loaded {song.mi3.name}：{len(song.variants)} music resources, {len(song.pcm)} audio tracks')
        self.write('Research build: original instrument sounds, mixing and startup offsets are approximate. Use offsets to calibrate.')
        for warning in song.warnings:
            self.write('Note: ' + warning)
        if self.presentation:
            self.presentation.on_song_loaded(song)
        self.apply()

    def settings_changed(self, event=None):
        if self.song and (not self.loading):
            self.apply()

    def apply(self):
        if self.song is None:
            return
        try:
            index = max(0, self.variant_box.current())
            self.ensure_routes()
            audio_offset, midi_offset = (float(self.offset_audio.get()), float(self.offset_midi.get()))
            if not (-10000 <= audio_offset <= 10000 and -10000 <= midi_offset <= 10000):
                raise ValueError('Offsets must be between -10000 and 10000 ms')
            settings = Settings(mode=MODES[self.mode_var.get()], audio_device=self.audio_lookup[self.audio_var.get()], midi_devices=tuple((self.midi_lookup[v.get()] for v in self.midi_vars)), midi_sources=tuple((0 if v.get() == 'Source A' else 1 for v in self.midi_source_vars)), track_routes={track: tuple(sorted(ports)) for track, ports in self.route_maps[index].items()}, audio_offset=audio_offset / 1000, midi_offset=midi_offset / 1000, master=self.master_var.get() / 100, gains=[v.get() / 100 for v in self.gain_vars])
            self.ready = False
            self.play_button.configure(state='disabled')
            self.engine.configure(self.song, index, settings)
            for warning in self.song.variants[index].warnings:
                self.write('Note: ' + warning)
        except Exception as ex:
            messagebox.showerror('Invalid settings', str(ex))

    def change_mix(self, value=None):
        if hasattr(self, 'gain_vars'):
            self.engine.command('mix', self.master_var.get() / 100, [v.get() / 100 for v in self.gain_vars])

    def play(self):
        if self.ready:
            self.engine.command('play')

    def seek(self, event=None):
        self.dragging = False
        if self.ready:
            self.engine.command('seek', float(self.timeline.get()))

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, generation, value = self.events.get_nowait()
                if generation != self.load_generation:
                    continue
                if kind == 'progress':
                    self.status.set(value)
                elif kind == 'loaded':
                    self.on_loaded(value)
                elif kind == 'load_error':
                    self.loading = False
                    self.status.set('Load failed')
                    self.write(value)
                    messagebox.showerror('Load failed', value)
        except queue.Empty:
            pass
        try:
            while True:
                kind, value = self.engine.messages.get_nowait()
                self.write(value)
                self.status.set(value)
                if kind == 'ready':
                    self.ready = True
                    self.play_button.configure(state='normal')
                elif kind == 'error':
                    self.ready = False
                    self.play_button.configure(state='disabled')
                    messagebox.showerror('Playback failed', value)
        except queue.Empty:
            pass
        position, duration, playing = self.engine.snapshot()
        self.timeline.configure(to=max(1, duration))
        if not self.dragging:
            self.timeline.set(position)
        self.time_var.set(f'{stamp(position)} / {stamp(duration)}')
        self.play_button.configure(text='Playing' if playing else 'Play / resume')
        self.root.after(80, self.poll)

    def close(self):
        self.closed = True
        if self.presentation:
            self.presentation.close()
        self.engine.close()
        self.root.destroy()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mi3', default='')
    ap.add_argument('--sd3', default='')
    args = ap.parse_args()
    root = tk.Tk()
    app = App(root, args.mi3, args.sd3)
    root.report_callback_exception = lambda kind, ex, trace: (logging.error('GUI error', exc_info=(kind, ex, trace)), messagebox.showerror('Interface error', str(ex)))
    logging.info('GUI ready')
    if args.mi3:
        root.after(150, app.load)
    root.mainloop()
if __name__ == '__main__':
    main()
