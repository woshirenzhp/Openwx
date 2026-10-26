"""Line and per-character timing model and Tk timeline editor (millisecond inputs)."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from difflib import SequenceMatcher
import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import lyrics
from lyrics import Cue

def sing(cue):
    return cue.start if cue.sing_start is None else cue.sing_start

def seconds(value):
    parts = str(value).strip().split(':')
    result = 0.0
    for part in parts:
        result = result * 60 + float(part)
    if not math.isfinite(result):
        raise ValueError('Time must be a finite number')
    return round(result, 3)

class TimelineModel:

    def __init__(self, cues):
        self.cues = deepcopy(cues)
        self.past, self.future = ([], [])

    @staticmethod
    def validate(cue):
        if not all((math.isfinite(v) for v in (cue.start, sing(cue), cue.end))) or not 0 <= cue.start <= sing(cue) <= cue.end or cue.end <= cue.start:
            raise ValueError('Required: display <= highlight start <= clear, with clear later than display')
        for a, b, l, r in cue.spans:
            if not all((math.isfinite(v) for v in (a, b))) or a > b or (not 0 <= l < r <= len(cue.text)):
                raise ValueError('Invalid character or segment timing')
            if not 0 <= a <= b <= cue.end - cue.start + 1e-06:
                raise ValueError('Character times must remain inside the line; adjust the character or line times first')

    def remember(self, previous=None):
        self.past.append(deepcopy(self.cues if previous is None else previous))
        self.past = self.past[-100:]
        self.future.clear()

    def put(self, index, cue, remember=True):
        cue = replace(cue)
        self.validate(cue)
        if remember:
            self.remember()
        self.cues[index] = cue

    def update_line(self, index, start, color, end, text):
        old = self.cues[index]
        delta = color - start - (sing(old) - old.start)
        mapping = {a + i: b + i for a, b, size in SequenceMatcher(None, old.text, text, autojunk=False).get_matching_blocks() for i in range(size)}
        spans = []
        for a, b, left, right in old.spans:
            positions = [mapping.get(i) for i in range(left, right)]
            if positions and positions[0] is not None and (positions == list(range(positions[0], positions[0] + len(positions)))):
                spans.append((a + delta, b + delta, positions[0], positions[-1] + 1))
        self.put(index, Cue(start, end, text, spans, color, old.timing_source))

    def shift(self, indices, offset):
        if not math.isfinite(offset):
            raise ValueError('Offset must be a finite number')
        if not indices:
            raise ValueError('Select a lyric line first')
        updated = {i: replace(self.cues[i], start=round(self.cues[i].start + offset, 3), end=round(self.cues[i].end + offset, 3), sing_start=round(sing(self.cues[i]) + offset, 3)) for i in indices}
        for cue in updated.values():
            self.validate(cue)
        self.remember()
        for i, cue in updated.items():
            self.cues[i] = cue

    def add(self, position):
        self.remember()
        index = next((i for i, cue in enumerate(self.cues) if cue.start > position), len(self.cues))
        self.cues.insert(index, Cue(position, position + 3, 'New lyric', sing_start=position))
        return index

    def delete(self, indices):
        if indices:
            self.remember()
            for index in sorted(set(indices), reverse=True):
                del self.cues[index]

    def undo(self):
        if self.past:
            self.future.append(deepcopy(self.cues))
            self.cues = self.past.pop()

    def redo(self):
        if self.future:
            self.past.append(deepcopy(self.cues))
            self.cues = self.future.pop()

    def char_time(self, row, char):
        cue = self.cues[row]
        matches = [(a + cue.start, b + cue.start) for a, b, l, r in cue.spans if l == char and r == char + 1]
        return matches[-1] if matches else None

    def set_char(self, row, char, start, end, remember=True):
        cue = self.cues[row]
        if not 0 <= char < len(cue.text):
            raise ValueError('Select a character')
        if not all((math.isfinite(v) for v in (start, end))) or not cue.start <= start < end <= cue.end:
            raise ValueError('Character times must fall within the line display/clear interval, with end later than start')
        if any((l <= char < r and r - l > 1 for a, b, l, r in cue.spans)):
            raise ValueError('This character is part of a timed segment; use Split segments first')
        spans = [s for s in cue.spans if not (s[2] == char and s[3] == char + 1)]
        spans.append((round(start - cue.start, 6), round(end - cue.start, 6), char, char + 1))
        self.put(row, replace(cue, spans=sorted(spans, key=lambda s: s[2])), remember)

    def clear_char(self, row, chars):
        cue = self.cues[row]
        self.put(row, replace(cue, spans=[s for s in cue.spans if not (s[3] - s[2] == 1 and s[2] in chars)]))

    def nudge_chars(self, row, chars, delta, edge):
        if not chars or not math.isfinite(delta) or edge not in ('start', 'end', 'move'):
            raise ValueError('Select timed characters and enter a valid nudge step')
        cue = self.cues[row]
        spans = list(cue.spans)
        for char in chars:
            timing = self.char_time(row, char)
            if timing is None:
                raise ValueError('Selected characters need individual timing; time them or split syllables first')
            a, b = timing
            a = round(a + (delta if edge in ('start', 'move') else 0), 3)
            b = round(b + (delta if edge in ('end', 'move') else 0), 3)
            if not cue.start <= a < b <= cue.end:
                raise ValueError('Nudged character times must remain inside the line, with end after start')
            spans = [s for s in spans if not (s[2] == char and s[3] == char + 1)]
            spans.append((round(a - cue.start, 6), round(b - cue.start, 6), char, char + 1))
        self.put(row, replace(cue, spans=sorted(spans, key=lambda s: s[2])))

    def split_segments(self, row):
        cue = self.cues[row]
        spans = []
        for a, b, left, right in cue.spans:
            for char in range(left, right):
                step = (b - a) / (right - left)
                spans.append((a + step * (char - left), a + step * (char - left + 1), char, char + 1))
        self.put(row, replace(cue, spans=spans))

    def distribute(self, row):
        cue = self.cues[row]
        chars = [i for i, ch in enumerate(cue.text) if ch != '\n']
        if not chars or sing(cue) >= cue.end:
            raise ValueError('Nonempty lyrics and a positive highlight interval are required')
        step = (cue.end - sing(cue)) / len(chars)
        self.put(row, replace(cue, spans=[(sing(cue) - cue.start + n * step, sing(cue) - cue.start + (n + 1) * step, char, char + 1) for n, char in enumerate(chars)]))

class TimelineEditor:

    def __init__(self, owner, live=False):
        self.owner = owner
        self.live = live
        self.draft_job = None
        self.model = TimelineModel(owner.cues)
        self.revision = owner.cues_revision
        self.selected = self.selected_char = None
        self.refreshing = False
        self.drag = None
        self.closed = False
        self.window = tk.Toplevel(owner.app.root)
        win = self.window
        win.title('Preview lyric editor · Live lines / characters · 0.001 s' if live else 'Lyric timeline - Lines / Characters - 0.001 second input')
        win.geometry('1220x900')
        win.minsize(1050, 780)
        win.protocol('WM_DELETE_WINDOW', self.close)
        self.status = tk.StringVar(win, value='Untimed characters remain blank. Timestamp characters individually, or generate an explicit evenly spaced draft and adjust it.')
        self.auto = tk.BooleanVar(win, value=live)
        self.auto_text = tk.BooleanVar(win, value=live)
        self.line_zoom = tk.DoubleVar(win, value=8)
        self.char_zoom = tk.DoubleVar(win, value=100)
        self.shift_amount = tk.StringVar(win, value='0.100')
        top = ttk.Frame(win, padding=8)
        top.pack(fill='x')
        for index, (label, callback) in enumerate([('Import...', self.load), ('Add line', self.add), ('Delete selected', self.delete), ('Undo', self.undo), ('Redo', self.redo), ('Play', owner.play), ('Pause', owner.pause), ('Apply to preview', self.apply_preview), ('Save timeline...', self.save)]):
            ttk.Button(top, text=label, command=callback).grid(row=index // 5, column=index % 5, sticky='ew', padx=2, pady=2)
        ttk.Checkbutton(top, text='Auto apply', variable=self.auto).grid(row=1, column=4)
        ttk.Checkbutton(top, text='Auto-commit line input', variable=self.auto_text, command=self.schedule_draft).grid(row=2, column=0, columnspan=2, sticky='w')
        ttk.Button(top, text='Find current lyric line', command=self.select_current).grid(row=2, column=2, columnspan=2, sticky='w')
        self.tree = ttk.Treeview(win, columns=('text', 'start', 'sing', 'end'), show='headings', height=6, selectmode='extended')
        for col, title, width in [('text', 'Lyrics (multiple selection)', 650), ('start', 'Display / s', 140), ('sing', 'Highlight start / s', 140), ('end', 'Clear / s', 140)]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=col == 'text')
        wrapper = ttk.Frame(win)
        wrapper.pack(fill='x', padx=8)
        self.tree.pack(in_=wrapper, side='left', fill='x', expand=True)
        scroll = ttk.Scrollbar(wrapper, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self.select_line)
        self.tree.bind('<Double-1>', lambda e: self.seek_selected())
        form = ttk.Frame(win, padding=8)
        form.pack(fill='x')
        self.text = tk.Text(form, height=2, width=50, font=('Segoe UI', 11), undo=True)
        self.text.pack(side='left', fill='x', expand=True)
        self.times = [tk.StringVar(win) for _ in range(3)]
        for label, variable in zip(('Display', 'Highlight', 'Clear'), self.times):
            ttk.Label(form, text=label).pack(side='left', padx=(8, 3))
            ttk.Entry(form, textvariable=variable, width=10).pack(side='left')
        ttk.Button(form, text='Commit line', command=self.commit_line).pack(side='left', padx=6)
        controls = ttk.Frame(win, padding=(8, 0, 8, 5))
        controls.pack(fill='x')
        for field, label in enumerate(('Mark display (F4)', 'Mark highlight (F5)', 'Mark clear (F6)')):
            ttk.Button(controls, text=label, command=lambda f=field: self.mark_line(f)).pack(side='left', padx=2)
            win.bind(f'<F{field + 4}>', lambda e, f=field: self.mark_line(f))
        ttk.Button(controls, text='Seek to selected', command=self.seek_selected).pack(side='left', padx=6)
        ttk.Label(controls, text='Shift selected (s)').pack(side='left', padx=(10, 3))
        ttk.Entry(controls, textvariable=self.shift_amount, width=9).pack(side='left')
        ttk.Button(controls, text='Shift lines', command=self.shift).pack(side='left', padx=4)
        self.clock_label = ttk.Label(controls)
        self.clock_label.pack(side='right')
        notebook = ttk.Notebook(win)
        notebook.pack(fill='both', expand=True, padx=8)
        line_tab, char_tab = (ttk.Frame(notebook), ttk.Frame(notebook))
        notebook.add(line_tab, text='Line timeline')
        notebook.add(char_tab, text='Character timeline')
        self.line_canvas = self.make_canvas(line_tab)
        zoom = ttk.Frame(line_tab)
        zoom.pack(fill='x')
        ttk.Label(zoom, text='Zoom (px/s)').pack(side='left')
        ttk.Spinbox(zoom, from_=1, to=1000, textvariable=self.line_zoom, width=8, command=self.draw).pack(side='left')
        ttk.Button(zoom, text='Apply zoom', command=self.draw).pack(side='left', padx=5)
        ttk.Label(zoom, text='Blue: display. Yellow: highlight. Red: clear. Drag handles or bars; click the ruler to seek.').pack(side='left')
        chars_top = ttk.Frame(char_tab)
        chars_top.pack(fill='x')
        self.char_tree = ttk.Treeview(chars_top, columns=('char', 'start', 'end', 'state'), show='headings', height=5, selectmode='extended')
        for col, label, width in [('char', 'Character index / text', 300), ('start', 'Character start / s', 180), ('end', 'Character end / s', 180), ('state', 'Timing status', 300)]:
            self.char_tree.heading(col, text=label)
            self.char_tree.column(col, width=width, stretch=col in ('char', 'state'))
        self.char_tree.pack(side='left', fill='x', expand=True)
        scroll = ttk.Scrollbar(chars_top, orient='vertical', command=self.char_tree.yview)
        scroll.pack(side='right', fill='y')
        self.char_tree.configure(yscrollcommand=scroll.set)
        self.char_tree.bind('<<TreeviewSelect>>', self.select_char)
        row = ttk.Frame(char_tab, padding=5)
        row.pack(fill='x')
        self.char_times = [tk.StringVar(win), tk.StringVar(win)]
        for label, value in zip(('Char start', 'Char end'), self.char_times):
            ttk.Label(row, text=label).pack(side='left', padx=3)
            ttk.Entry(row, textvariable=value, width=11).pack(side='left')
        for label, callback in [('Commit character', self.commit_char), ('Mark start (F7)', self.mark_char_start), ('Mark end / next (F8)', self.mark_char_end), ('Clear selected timing', self.clear_chars)]:
            ttk.Button(row, text=label, command=callback).pack(side='left', padx=3)
        row = ttk.Frame(char_tab, padding=(5, 0))
        row.pack(fill='x')
        ttk.Button(row, text='Split segments (even spacing)', command=self.split).pack(side='left')
        ttk.Button(row, text='Even draft (not original timing)', command=self.distribute).pack(side='left', padx=6)
        ttk.Label(row, text='Character zoom (px/s)').pack(side='left')
        ttk.Spinbox(row, from_=10, to=1000, textvariable=self.char_zoom, width=7, command=self.draw).pack(side='left')
        ttk.Button(row, text='Refresh', command=self.draw).pack(side='left')
        row = ttk.Frame(char_tab, padding=5)
        row.pack(fill='x')
        self.char_nudge_ms = tk.StringVar(win, value='10')
        ttk.Label(row, text='Character nudge step ms').pack(side='left')
        ttk.Spinbox(row, from_=1, to=60000, increment=1, textvariable=self.char_nudge_ms, width=7).pack(side='left', padx=3)
        for edge, label in [('start', 'Start'), ('end', 'End'), ('move', 'Move')]:
            for direction, sign in [(-1, '−'), (1, '+')]:
                ttk.Button(row, text=label + ' ' + sign, command=lambda e=edge, d=direction: self.nudge_char(e, d)).pack(side='left', padx=2)
        self.char_canvas = self.make_canvas(char_tab)
        for canvas, kind in ((self.line_canvas, 'line'), (self.char_canvas, 'char')):
            canvas.bind('<Button-1>', lambda e, k=kind: self.drag_start(e, k))
            canvas.bind('<B1-Motion>', self.drag_move)
            canvas.bind('<ButtonRelease-1>', self.drag_end)
        win.bind('<F7>', lambda e: self.mark_char_start())
        win.bind('<F8>', lambda e: self.mark_char_end())
        ttk.Label(win, textvariable=self.status, wraplength=1180, padding=8).pack(fill='x')
        self.refresh(0 if self.model.cues else None)
        self.text.bind('<<Modified>>', self.text_modified)
        for variable in self.times:
            variable.trace_add('write', lambda *args: self.schedule_draft())
        self.after = win.after(70, self.poll)

    def make_canvas(self, parent):
        wrapper = ttk.Frame(parent)
        wrapper.pack(fill='both', expand=True)
        canvas = tk.Canvas(wrapper, background='#182131', highlightthickness=0, height=190)
        canvas.grid(row=0, column=0, sticky='nsew')
        x = ttk.Scrollbar(wrapper, orient='horizontal', command=canvas.xview)
        y = ttk.Scrollbar(wrapper, orient='vertical', command=canvas.yview)
        x.grid(row=1, column=0, sticky='ew')
        y.grid(row=0, column=1, sticky='ns')
        canvas.configure(xscrollcommand=x.set, yscrollcommand=y.set)
        wrapper.rowconfigure(0, weight=1)
        wrapper.columnconfigure(0, weight=1)
        return canvas

    def operation(self, callback, select=None, message='Changed (undo available). Save JSON/CSV to retain character start/end times.'):
        try:
            if self.auto_text.get() and (not self.commit_line(automatic=True)):
                return
            callback()
            self.refresh(self.selected if select is None else select)
            self.status.set(message)
            if self.auto.get():
                self.apply_preview()
        except Exception as ex:
            self.status.set(str(ex))

    def refresh(self, select=None):
        self.refreshing = True
        self.tree.delete(*self.tree.get_children())
        for i, cue in enumerate(self.model.cues):
            self.tree.insert('', 'end', iid=str(i), values=(f'{i + 1}. ' + cue.text.replace('\n', ' / '), f'{cue.start:.3f}', f'{sing(cue):.3f}', f'{cue.end:.3f}'))
        if select is not None and self.model.cues:
            select = min(select, len(self.model.cues) - 1)
            self.tree.selection_set(str(select))
            self.tree.see(str(select))
        self.refreshing = False
        self.selected = None
        self.select_line()

    def select_line(self, event=None):
        if self.refreshing:
            return
        items = self.tree.selection()
        selected = int(items[0]) if items else None
        if selected is not None and selected == self.selected:
            return
        if self.auto_text.get() and self.selected is not None and (not self.commit_line(automatic=True)):
            self.refreshing = True
            self.tree.selection_set(str(self.selected))
            self.refreshing = False
            return
        self.selected = selected
        self.refreshing = True
        try:
            self.text.delete('1.0', 'end')
            if self.selected is not None:
                cue = self.model.cues[self.selected]
                self.text.insert('1.0', cue.text)
                for value, number in zip(self.times, (cue.start, sing(cue), cue.end)):
                    value.set(f'{number:.3f}')
            else:
                for value in self.times:
                    value.set('')
            self.text.edit_modified(False)
            self.text.edit_reset()
        finally:
            self.refreshing = False
        self.refresh_chars()
        self.draw()

    def refresh_chars(self, select=None):
        self.char_tree.delete(*self.char_tree.get_children())
        if self.selected is None:
            self.selected_char = None
            return
        cue = self.model.cues[self.selected]
        for index, char in enumerate(cue.text):
            timing = self.model.char_time(self.selected, index)
            grouped = any((l <= index < r and r - l > 1 for a, b, l, r in cue.spans))
            self.char_tree.insert('', 'end', iid=str(index), values=(f'{index + 1}. ' + {'\n': '↵', ' ': 'Space'}.get(char, char), f'{timing[0]:.3f}' if timing else '', f'{timing[1]:.3f}' if timing else '', ('Estimated template; editable' if cue.timing_source.startswith('estimated') else 'Character timing') if timing else 'Segment timing: split to refine' if grouped else 'Untimed'))
        if cue.text:
            select = min(select if select is not None else self.selected_char or 0, len(cue.text) - 1)
            self.char_tree.selection_set(str(select))
            self.char_tree.see(str(select))
        self.select_char()

    def select_char(self, event=None):
        items = self.char_tree.selection()
        self.selected_char = int(items[0]) if items else None
        timing = self.model.char_time(self.selected, self.selected_char) if self.selected is not None and self.selected_char is not None else None
        for variable, number in zip(self.char_times, timing or ('', '')):
            variable.set(f'{number:.3f}' if isinstance(number, (int, float)) else '')

    def text_modified(self, event=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.schedule_draft()

    def schedule_draft(self):
        if self.draft_job:
            self.window.after_cancel(self.draft_job)
            self.draft_job = None
        if not self.closed and (not self.refreshing) and self.auto_text.get():
            self.draft_job = self.window.after(350, self.flush_draft)

    def flush_draft(self):
        self.draft_job = None
        self.commit_line(automatic=True)

    def commit_line(self, automatic=False):
        if self.draft_job:
            self.window.after_cancel(self.draft_job)
            self.draft_job = None
        if self.selected is None:
            return True
        try:
            cue = self.model.cues[self.selected]
            start, color, end = [seconds(t.get()) for t in self.times]
            text = self.text.get('1.0', 'end-1c')
            if (start, color, end, text) == (cue.start, sing(cue), cue.end, cue.text):
                return True
            self.model.update_line(self.selected, start, color, end, text)
            self.tree.item(str(self.selected), values=(f'{self.selected + 1}. ' + text.replace('\n', ' / '), f'{start:.3f}', f'{color:.3f}', f'{end:.3f}'))
            self.refresh_chars()
            self.draw()
            self.status.set('Line committed; unchanged text keeps its timing. Time new or replaced characters as needed.')
            if self.auto.get():
                self.apply_preview()
            return True
        except Exception as ex:
            self.status.set(str(ex))
            return False

    def select_current(self):
        if not self.model.cues:
            return
        position = self.owner.position() - self.owner.lyric_offset
        active = [i for i, cue in enumerate(self.model.cues) if sing(cue) <= position < cue.end]
        index = max(active, key=lambda i: sing(self.model.cues[i])) if active else min(range(len(self.model.cues)), key=lambda i: abs(self.model.cues[i].start - position))
        self.tree.selection_set(str(index))
        self.tree.see(str(index))
        self.select_line()

    def nudge_char(self, edge, direction):
        if self.selected is None:
            return
        selected = tuple(self.char_tree.selection())

        def action():
            step = float(self.char_nudge_ms.get())
            if not math.isfinite(step) or not 1 <= step <= 60000:
                raise ValueError('Character nudge step must be between 1 and 60000 ms')
            self.model.nudge_chars(self.selected, {int(i) for i in self.char_tree.selection()}, direction * step / 1000, edge)
        self.operation(action)
        surviving = [item for item in selected if self.char_tree.exists(item)]
        if surviving:
            self.char_tree.selection_set(*surviving)
            self.select_char()

    def mark_line(self, index):
        self.times[index].set(f'{max(0, self.owner.position() - self.owner.lyric_offset):.3f}')

    def mark_char_start(self):
        self.char_times[0].set(f'{max(0, self.owner.position() - self.owner.lyric_offset):.3f}')

    def mark_char_end(self):
        self.char_times[1].set(f'{max(0, self.owner.position() - self.owner.lyric_offset):.3f}')
        if self.commit_char() and self.selected_char is not None:
            next_char = self.selected_char + 1
            self.refresh_chars(next_char)

    def commit_char(self):
        if self.selected is None or self.selected_char is None:
            return False
        try:
            self.model.set_char(self.selected, self.selected_char, *[seconds(t.get()) for t in self.char_times])
            self.refresh_chars(self.selected_char)
            self.draw()
            self.status.set('Character start/end times saved at millisecond precision.')
            if self.auto.get():
                self.apply_preview()
            return True
        except Exception as ex:
            self.status.set(str(ex))
            return False

    def clear_chars(self):
        if self.selected is not None:
            self.operation(lambda: self.model.clear_char(self.selected, {int(i) for i in self.char_tree.selection()}))

    def split(self):
        if self.selected is not None:
            self.operation(lambda: self.model.split_segments(self.selected), message='Segments split evenly into characters. This is an estimated draft; adjust it as needed.')

    def distribute(self):
        if self.selected is not None:
            self.operation(lambda: self.model.distribute(self.selected), message='Generated an evenly spaced draft; these are not original MI3 character timestamps.')

    def add(self):
        if self.auto_text.get() and (not self.commit_line(automatic=True)):
            return
        index = self.model.add(round(max(0, self.owner.position() - self.owner.lyric_offset), 3))
        self.refresh(index)
        if self.auto.get():
            self.apply_preview()

    def delete(self):
        self.operation(lambda: self.model.delete([int(i) for i in self.tree.selection()]))

    def shift(self):
        self.operation(lambda: self.model.shift([int(i) for i in self.tree.selection()], seconds(self.shift_amount.get())))

    def undo(self):
        self.operation(self.model.undo)

    def redo(self):
        self.operation(self.model.redo)

    def seek_selected(self):
        if self.selected is not None:
            self.owner.seek(max(0, self.model.cues[self.selected].start + self.owner.lyric_offset))

    def apply_preview(self):
        if self.owner.cues_revision != self.revision:
            self.status.set('Lyrics were replaced in another window. Open a new timeline to apply edits; you can still save this draft.')
            return
        self.owner.set_cues(sorted(deepcopy(self.model.cues), key=lambda cue: cue.start), 'Timeline edits')
        self.revision = self.owner.cues_revision
        self.status.set('Applied to preview and subsequent exports; the source MI3 is unchanged.')

    def save(self):
        if self.auto_text.get() and (not self.commit_line(automatic=True)):
            return
        from subtitle_formats import EXPORT_TYPES
        path = filedialog.asksaveasfilename(parent=self.window, defaultextension='.json', filetypes=EXPORT_TYPES)
        if path:
            try:
                lyrics.protect_source(path, getattr(getattr(self.owner, 'app', None), 'song', None))
                lyrics.save_cues(path, self.model.cues, self.owner.filter_numeric.get())
                self.status.set(('Saved with filtering: ' if self.owner.filter_numeric.get() else 'Saved with original text: ') + path + ('; LRC retains line highlight starts only. Use JSON/CSV for character start/end times.' if Path(path).suffix.lower() == '.lrc' else ''))
            except Exception as ex:
                self.status.set(str(ex))

    def load(self):
        from subtitle_formats import IMPORT_PATTERN
        path = filedialog.askopenfilename(parent=self.window, filetypes=[('Lyrics / timeline', IMPORT_PATTERN)])
        if path:
            try:
                cues = lyrics.load(path)
                for cue in cues:
                    TimelineModel.validate(cue)
                self.model.remember()
                self.model.cues = cues
                self.refresh(0 if cues else None)
            except Exception as ex:
                self.status.set(str(ex))

    def scale(self, kind):
        variable = self.line_zoom if kind == 'line' else self.char_zoom
        return min(1000, max(1, float(variable.get())))

    def draw(self):
        try:
            self.draw_canvas(self.line_canvas, 'line')
            self.draw_canvas(self.char_canvas, 'char')
        except (ValueError, tk.TclError):
            pass

    def draw_canvas(self, canvas, kind):
        canvas.delete('all')
        scale = self.scale(kind)
        origin = 0 if kind == 'line' or self.selected is None else self.model.cues[self.selected].start
        duration = max([1] + [c.end for c in self.model.cues]) if kind == 'line' else self.model.cues[self.selected].end - origin if self.selected is not None else 5
        count = len(self.model.cues) if kind == 'line' else len(self.model.cues[self.selected].text) if self.selected is not None else 0
        width, height = (max(1000, 120 + duration * scale), max(190, 45 + count * 28))
        canvas.configure(scrollregion=(0, 0, width, height))
        step = next((s for s in (0.1, 0.5, 1, 2, 5, 10, 30, 60, 300, 600) if s * scale >= 75), 600)
        for tick in range(int(duration / step) + 2):
            x = 100 + tick * step * scale
            canvas.create_line(x, 25, x, height, fill='#33425a')
            canvas.create_text(x + 2, 12, text=f'{origin + tick * step:.3f}', fill='#b9c5d8', anchor='w')
        for i in range(count):
            y = 35 + i * 28
            if kind == 'line':
                cue = self.model.cues[i]
                start, color, end = (cue.start, sing(cue), cue.end)
                label = f'{i + 1} ' + cue.text[:8]
            else:
                cue = self.model.cues[self.selected]
                timing = self.model.char_time(self.selected, i)
                label = f'{i + 1} ' + cue.text[i].replace('\n', '↵')
                if timing is None:
                    canvas.create_text(8, y + 8, text=label + '  Untimed', fill='#92a1b8', anchor='w')
                    continue
                start, end = timing
                color = start
            x1, xs, x2 = [100 + (t - origin) * scale for t in (start, color, end)]
            canvas.create_rectangle(x1, y, max(x1 + 2, x2), y + 20, fill='#476d96', outline='#b1d6ff', tags=(f'bar:{kind}:{i}',))
            canvas.create_rectangle(xs, y + 12, max(xs + 1, x2), y + 19, fill='#e4bf3f', outline='', tags=(f'bar:{kind}:{i}',))
            canvas.create_text(max(3, x1 + 4), y + 8, text=label, fill='white', anchor='w', tags=(f'bar:{kind}:{i}',))
            for label, x, color, dy in [('start', x1, '#58c7ff', 0), ('sing', xs, '#ffe16a', 6), ('end', x2, '#ff7388', 12)]:
                if kind == 'char' and label == 'sing':
                    continue
                canvas.create_rectangle(x - 4, y + dy, x + 4, y + dy + 8, fill=color, outline='', tags=(f'handle:{kind}:{i}:{label}',))
        current = self.owner.position() - self.owner.lyric_offset
        x = 100 + (current - origin) * scale
        canvas.create_line(x, 0, x, height, fill='#ff5d6b', width=2, tags=('playhead',))

    def drag_start(self, event, kind):
        canvas = self.line_canvas if kind == 'line' else self.char_canvas
        x, y = (canvas.canvasx(event.x), canvas.canvasy(event.y))
        if y < 28:
            origin = 0 if kind == 'line' or self.selected is None else self.model.cues[self.selected].start
            self.owner.seek(max(0, origin + (x - 100) / self.scale(kind) + self.owner.lyric_offset))
            return
        items = canvas.find_overlapping(x - 2, y - 2, x + 2, y + 2)
        tag = next((tag for item in reversed(items) for tag in canvas.gettags(item) if tag.startswith('handle:')), None)
        if tag:
            _, _, index, mode = tag.split(':')
        else:
            tag = next((tag for item in reversed(items) for tag in canvas.gettags(item) if tag.startswith('bar:')), None)
            if not tag:
                return
            _, _, index = tag.split(':')
            mode = 'move'
        index = int(index)
        if kind == 'line':
            self.tree.selection_set(str(index))
            self.tree.see(str(index))
            row = index
        else:
            row = self.selected
            self.char_tree.selection_set(str(index))
            self.char_tree.see(str(index))
        self.drag = dict(kind=kind, row=row, char=index, mode=mode, x=x, before=deepcopy(self.model.cues), cue=deepcopy(self.model.cues[row]))

    def drag_move(self, event):
        if not self.drag:
            return
        drag = self.drag
        canvas = self.line_canvas if drag['kind'] == 'line' else self.char_canvas
        delta = round((canvas.canvasx(event.x) - drag['x']) / self.scale(drag['kind']), 3)
        old = drag['cue']
        try:
            if drag['kind'] == 'line':
                a, b, c = (old.start, sing(old), old.end)
                if drag['mode'] == 'move':
                    delta = max(-a, delta)
                    cue = replace(old, start=a + delta, end=c + delta, sing_start=b + delta)
                else:
                    values = dict(start=a, sing_start=b, end=c)
                    if drag['mode'] == 'start':
                        values['start'] = min(b, max(0, a + delta))
                    elif drag['mode'] == 'end':
                        values['end'] = max(b, a + 0.001, c + delta)
                    else:
                        values['sing_start'] = min(c, max(a, b + delta))
                    shift = values['sing_start'] - values['start'] - (b - a)
                    cue = replace(old, **values, spans=[(s + shift, e + shift, l, r) for s, e, l, r in old.spans])
                self.model.put(drag['row'], cue, remember=False)
            else:
                a, b = next(((s + old.start, e + old.start) for s, e, l, r in old.spans if l == drag['char'] and r == l + 1))
                if drag['mode'] == 'start':
                    a = min(b - 0.001, max(old.start, a + delta))
                elif drag['mode'] == 'end':
                    b = max(a + 0.001, min(old.end, b + delta))
                else:
                    delta = min(old.end - b, max(old.start - a, delta))
                    a, b = (a + delta, b + delta)
                self.model.cues[drag['row']] = deepcopy(old)
                self.model.set_char(drag['row'], drag['char'], a, b, remember=False)
            self.draw()
        except (ValueError, StopIteration):
            pass

    def drag_end(self, event=None):
        if self.drag:
            drag, self.drag = (self.drag, None)
            if self.model.cues != drag['before']:
                self.model.remember(drag['before'])
            self.refresh(drag['row'])
            if drag['kind'] == 'char':
                self.refresh_chars(drag['char'])
            if self.auto.get():
                self.apply_preview()

    def poll(self):
        if self.closed:
            return
        position = self.owner.position() - self.owner.lyric_offset
        self.clock_label.configure(text=f'Lyric time {position:.3f} s')
        for canvas, kind in ((self.line_canvas, 'line'), (self.char_canvas, 'char')):
            try:
                origin = 0 if kind == 'line' or self.selected is None else self.model.cues[self.selected].start
                x = 100 + (position - origin) * self.scale(kind)
                canvas.coords('playhead', x, 0, x, max(190, float(canvas.cget('scrollregion').split()[-1])))
            except (tk.TclError, ValueError):
                pass
        self.after = self.window.after(70, self.poll)

    def close(self):
        if not self.closed:
            if self.auto_text.get():
                self.commit_line(automatic=True)
            self.closed = True
            if self.draft_job:
                self.window.after_cancel(self.draft_job)
                self.draft_job = None
            self.window.after_cancel(self.after)
            self.window.destroy()
