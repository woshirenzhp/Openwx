"""Tk project commands; worker threads only handle files and media decoding."""
from dataclasses import asdict
from pathlib import Path
import queue
import threading
from tkinter import filedialog, messagebox
import projects
from lyrics import Cue
from media import default_font

class ProjectController:

    def __init__(self, app):
        self.app = app
        self.events = queue.Queue()
        self.busy = False
        self.current = None
        self.pending_ready = None
        self.base_title = app.root.title()

    def presentation(self):
        if self.app.presentation is None:
            from presentation import Presentation
            self.app.presentation = Presentation(self.app)
        return self.app.presentation

    @staticmethod
    def descriptor(variable, lookup):
        label = variable.get()
        index = lookup[label]
        return None if index is None else {'id': index, 'name': label.split(': ', 1)[-1]}

    def capture(self):
        from app import MODES
        from presentation import EXPORT_FORMATS
        a = self.app
        p = self.presentation()
        current = [e for e in p.editors if not e.closed and e.revision == p.cues_revision]
        if current:
            editor = current[-1]
            if not editor.commit_line():
                raise ValueError('Correct invalid lyric editor input before saving the project')
            editor.apply_preview()
        if not p.apply():
            raise ValueError('Correct the video or lyric style settings first')
        resources = []
        paths = {}
        ids = {}

        def link(value, font=False):
            if not value:
                return None
            path = Path(value).resolve()
            if not path.is_file():
                raise ValueError('Linked resource not found: ' + str(path))
            key = str(path).casefold()
            if key not in ids:
                rid = 'r' + str(len(resources))
                ids[key] = rid
                resources.append({'id': rid, 'builtin_font': font and path == Path(default_font()).resolve()})
                paths[rid] = path
            return ids[key]
        music = a.song.music_paths or ([a.song.mi3] if a.song.mi3 else []) if a.song else [a.mi3_path.get().strip()] if a.mi3_path.get().strip() else []
        audio = a.song.sd3 if a.song else a.sd3_path.get().strip() or None
        if a.song:
            entered_music = Path(a.mi3_path.get()).resolve() if a.mi3_path.get().strip() else None
            entered_audio = Path(a.sd3_path.get()).resolve() if a.sd3_path.get().strip() else None
            if entered_music != (Path(a.song.mi3).resolve() if a.song.mi3 else None) or entered_audio != (Path(audio).resolve() if audio else None):
                raise ValueError('Load the selected music/audio before saving the project')
        links = dict(music=[link(v) for v in music], audio=link(audio), visual=link(p.source.get()), font=link(p.font.get(), True))
        if a.song:
            a.ensure_routes()
        style = asdict(p.style)
        style.pop('font')
        data = dict(links=links, resources=resources, lyrics=[asdict(cue) for cue in p.cues], position=a.engine.position() if a.song and a.ready else p.position(), playback=dict(mode=MODES[a.mode_var.get()], variant=max(0, a.variant_box.current()), audio_offset=float(a.offset_audio.get()) / 1000, midi_offset=float(a.offset_midi.get()) / 1000, master=a.master_var.get() / 100, gains=[v.get() / 100 for v in a.gain_vars], audio_device=self.descriptor(a.audio_var, a.audio_lookup), midi_devices=[self.descriptor(v, a.midi_lookup) for v in a.midi_vars], midi_sources=[0 if v.get() == 'Source A' else 1 for v in a.midi_source_vars], routes={str(v): {str(track): sorted(ports) for track, ports in routes.items()} for v, routes in a.route_maps.items()}), presentation=dict(style=style, lyric_offset=p.lyric_offset, video_offset=p.video_offset, resolution=p.resolution.get(), fps=int(p.fps.get()), duration=float(p.duration.get()), local_position=p.position(), output_format=EXPORT_FORMATS[p.output_format.get()], audio={'No audio': 'none', 'Input video audio': 'video', 'Current audio mix': 'mix'}[p.audio.get()], panel_open=bool(p.window and p.window.winfo_exists()), previews=[v.green for v in p.previews if not v.closed], **{key: getattr(p, key).get() for key in ('follow', 'enable_preview', 'enable_export', 'filter_numeric', 'green_export')}))
        if not a.song:
            data['playback']['mode'] = 'audio' if audio and (not music) else 'midi' if music and (not audio) else 'auto'
        return (data, paths)

    def save(self, packed=False, reuse=False, path=None):
        if self.busy or self.app.loading:
            self.app.status.set('Wait for the current load or project operation to finish')
            return
        try:
            snapshot, paths = self.capture()
            suffix = '.opx' if packed else '.opw'
            if reuse and self.current:
                kind = projects.SUFFIXES[Path(self.current).suffix.lower()]
                path = Path(self.current).with_suffix('.opx' if kind == 'packed' else '.opw')
            if path is None:
                path = filedialog.asksaveasfilename(parent=self.app.root, defaultextension=suffix, filetypes=[('Packed project (with resources)' if packed else 'Reference project', '*' + suffix)])
            if not path:
                return
            if Path(path).suffix.lower() not in projects.SUFFIXES:
                raise ValueError('Project extension must be .opw or .opx')
            self.busy = True

            def work():
                try:
                    projects.write(path, snapshot, paths, lambda text: self.events.put(('progress', text)))
                    self.events.put(('saved', str(Path(path).resolve())))
                except Exception as ex:
                    self.events.put(('error', str(ex)))
            threading.Thread(target=work, daemon=True, name='Project save').start()
        except Exception as ex:
            messagebox.showerror('Project save failed', str(ex), parent=self.app.root)

    def open(self, path=None):
        if self.busy or self.app.loading:
            self.app.status.set('Wait for the current load or project operation to finish')
            return
        if path is None:
            path = filedialog.askopenfilename(parent=self.app.root, filetypes=[('Player project', '*.opw *.opx'), ('Legacy project', '*.mi3proj *.mi3pack')])
        if not path:
            return
        self.busy = True

        def work():
            try:
                data, paths = projects.read(path, lambda text: self.events.put(('progress', text)))
                self.events.put(('resolve', (path, data, paths)))
            except Exception as ex:
                self.events.put(('error', str(ex)))
        threading.Thread(target=work, daemon=True, name='Project open').start()

    def resolve(self, path, data, paths):
        a = self.app
        folders = []
        for item in data['resources']:
            rid = item['id']
            if rid in paths:
                continue
            found = next((folder / item['name'] for folder in folders if (folder / item['name']).is_file()), None)
            if found is None and item.get('builtin_font'):
                found = Path(default_font())
            if found is None:
                chosen = filedialog.askopenfilename(parent=a.root, title='Relocate missing resource: ' + item['name'], filetypes=[('All files', '*.*')])
                if not chosen:
                    self.busy = False
                    a.status.set('Project open cancelled; current session retained')
                    return
                found = Path(chosen)
                folders.append(found.parent)
            paths[rid] = found.resolve()

        def work():
            try:
                from song import load_song
                links = data['links']
                music = [paths[r] for r in links['music']]
                audio = paths.get(links['audio'])
                song = load_song(music, audio, lambda text: self.events.put(('progress', text))) if music or audio else None
                if links['font']:
                    from PIL import ImageFont
                    ImageFont.truetype(str(paths[links['font']]), data['presentation']['style']['size'])
                if links['visual']:
                    from media import Background
                    visual = Background(str(paths[links['visual']]))
                    visual.close()
                self.events.put(('restore', (path, data, paths, song)))
            except Exception as ex:
                self.events.put(('error', str(ex)))
        threading.Thread(target=work, daemon=True, name='Project media decode').start()

    def choose_device(self, desc, lookup, warnings):
        if desc is None:
            return next((label for label, value in lookup.items() if value is None))
        exact = next((label for label, value in lookup.items() if value == desc['id'] and label.split(': ', 1)[-1] == desc['name']), None)
        by_name = next((label for label, value in lookup.items() if value is not None and label.split(': ', 1)[-1] == desc['name']), None)
        if exact or by_name:
            return exact or by_name
        warnings.append('Device unavailable; default used or output disabled: ' + desc['name'])
        return next((label for label, value in lookup.items() if value is None))

    def restore(self, path, data, paths, song):
        from app import MODES
        from presentation import EXPORT_FORMATS
        a = self.app
        p = self.presentation()
        saved = data['presentation']
        settings = data['playback']
        links = data['links']
        warnings = []
        for item in data['resources']:
            if paths[item['id']].stat().st_size != item['size']:
                warnings.append('Resource size has changed; check synchronization: ' + item['name'])
        if song and settings['variant'] >= len(song.variants):
            raise ValueError('Project music resource index does not match the current file')
        if song:
            for vi, routes in settings['routes'].items():
                if int(vi) >= len(song.variants):
                    raise ValueError('Project routing references a missing music resource')
                known = {part.id for part in song.variants[int(vi)].parts}
                if any((int(track) not in known for track in routes)):
                    raise ValueError('Project routing does not match the current MIDI tracks')
        for view in p.previews:
            view.close()
        p.previews = []
        a.engine.command('stop')
        a.mi3_path.set(str(song.mi3) if song and song.mi3 else '')
        a.sd3_path.set(str(song.sd3) if song and song.sd3 else '')
        if song:
            a.on_loaded(song, apply_settings=False)
        else:
            a.engine.command('unload')
            a.song = None
            a.ready = False
            a.play_button.configure(state='disabled')
            a.variant_box['values'] = ()
            a.variant_var.set('')
            a.route_tree.delete(*a.route_tree.get_children())
            a.route_maps = {}
            a.route_index = None
            for widget in a.track_widgets:
                widget.destroy()
            a.track_widgets = []
            a.gain_vars = []
        a.mode_var.set(next((label for label, value in MODES.items() if value == settings['mode'])))
        a.offset_audio.set(str(settings['audio_offset'] * 1000))
        a.offset_midi.set(str(settings['midi_offset'] * 1000))
        a.master_var.set(settings['master'] * 100)
        for variable, gain in zip(a.gain_vars, settings['gains']):
            variable.set(gain * 100)
        a.audio_var.set(self.choose_device(settings['audio_device'], a.audio_lookup, warnings))
        used = set()
        for variable, desc in zip(a.midi_vars, settings['midi_devices']):
            label = self.choose_device(desc, a.midi_lookup, warnings)
            device = a.midi_lookup[label]
            if device is not None and device in used:
                label = self.choose_device(None, a.midi_lookup, warnings)
                warnings.append('Duplicate MIDI output disabled')
            elif device is not None:
                used.add(device)
            variable.set(label)
        for variable, value in zip(a.midi_source_vars, settings['midi_sources']):
            variable.set('Source A' if value == 0 else 'Source B')
        a.route_maps = {int(vi): {int(track): set(ports) for track, ports in routes.items()} for vi, routes in settings['routes'].items()}
        a.route_index = None
        if song:
            a.variant_box.current(settings['variant'])
            a.ensure_routes()
        style = saved['style']
        p.source.set(str(paths[links['visual']]) if links['visual'] else '')
        p.font.set(str(paths[links['font']]) if links['font'] else default_font())
        for attr, key in [('font_size', 'size'), ('stroke_width', 'stroke_width'), ('bottom', 'bottom'), ('page_lines', 'page_lines'), ('immediate_line_change', 'immediate_line_change'), ('timing_enabled', 'timing_enabled'), ('fill_early', 'fill_early')]:
            getattr(p, attr).set(style[key])
        for key, var in p.colors.items():
            var.set(style[key])
        for key, var in p.timing_vars.items():
            var.set(style[key])
        p.lyric_ms.set(str(saved['lyric_offset'] * 1000))
        p.video_ms.set(str(saved['video_offset'] * 1000))
        p.resolution.set(saved['resolution'])
        p.fps.set(str(saved['fps']))
        p.duration.set(str(saved['duration']))
        p.output_format.set(next((label for label, value in EXPORT_FORMATS.items() if value == saved['output_format'])))
        p.audio.set({'none': 'No audio', 'video': 'Input video audio', 'mix': 'Current audio mix'}[saved['audio']])
        for key in ('follow', 'enable_preview', 'enable_export', 'filter_numeric', 'green_export'):
            getattr(p, key).set(saved[key])
        p.set_cues([Cue(**row) for row in data['lyrics']], 'Project lyrics')
        p.local_position = saved['local_position']
        p.local_start = None
        if not p.apply():
            raise ValueError('Could not restore project styles')
        if saved['panel_open']:
            p.open()
        if p.window and p.window.winfo_exists():
            p.format_changed()
        for green in saved['previews']:
            if saved['enable_preview']:
                p.preview(green)
        self.current = Path(path).resolve()
        self.busy = False
        a.root.title(self.base_title + ' · ' + self.current.name)
        if song:
            self.pending_ready = (data['position'], saved['duration'])
            a.apply()
        else:
            self.pending_ready = None
        for warning in warnings:
            a.write(warning)
        a.status.set('Project opened; playback paused: ' + str(self.current))

    def on_ready(self):
        if self.pending_ready is None:
            return False
        position, duration = self.pending_ready
        self.pending_ready = None
        self.app.engine.command('seek', position)
        self.presentation().duration.set(str(duration))
        return True

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                try:
                    if kind == 'progress':
                        self.app.status.set(value)
                    elif kind == 'saved':
                        self.busy = False
                        self.current = Path(value)
                        self.app.status.set('Project saved: ' + value)
                        self.app.root.title(self.base_title + ' · ' + self.current.name)
                    elif kind == 'resolve':
                        self.resolve(*value)
                    elif kind == 'restore':
                        self.restore(*value)
                    elif kind == 'error':
                        raise ValueError(value)
                except Exception as ex:
                    self.busy = False
                    self.pending_ready = None
                    messagebox.showerror('Project operation failed', str(ex), parent=self.app.root)
        except queue.Empty:
            pass
