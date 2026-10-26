"""Scrollable lyric visibility settings; values are display-only milliseconds."""
import tkinter as tk
from tkinter import ttk

class TimingStyleDialog:

    def __init__(self, owner):
        self.owner = owner
        win = self.window = tk.Toplevel(owner.app.root)
        win.title('Lyric visibility timing')
        win.geometry('650x760')
        win.minsize(580, 560)
        background = '#12141e'
        win.configure(background=background)
        ui = ttk.Style(win)
        ui.configure('Timing.TCheckbutton', background=background, foreground='#e0e1ea')
        ui.map('Timing.TCheckbutton', background=[('active', background)])
        canvas = tk.Canvas(win, bg=background, highlightthickness=0)
        bar = ttk.Scrollbar(win, orient='vertical', command=canvas.yview)
        bar.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        canvas.configure(yscrollcommand=bar.set)
        panel = tk.Frame(canvas, bg=background, padx=20, pady=16)
        item = canvas.create_window(0, 0, window=panel, anchor='nw')
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
        panel.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<MouseWheel>', lambda e: canvas.yview_scroll(-int(e.delta / 120), 'units'))
        ttk.Checkbutton(panel, text='Enable visibility timing', variable=owner.timing_enabled, style='Timing.TCheckbutton').pack(anchor='w', pady=(0, 14))
        tk.Label(panel, text='Display-only settings; song and character timestamps are unchanged.', bg=background, fg='#999eaf', wraplength=570, justify='left').pack(anchor='w', pady=(0, 18))
        specs = [('advance_ms', 'Show before singing', 'Preferred lead time before singing, subject to slot availability', 10000), ('hold_ms', 'Hold after singing', 'Keep the line visible after its last character finishes, then fade out', 10000), ('fade_in_ms', 'Fade in (ease in)', '', 2000), ('fade_out_ms', 'Fade out (ease out)', '', 2000)]
        for name, label, hint, maximum in specs:
            self.control(panel, name, label, hint, maximum, background)
        ttk.Checkbutton(panel, text='Fill empty slots early', variable=owner.fill_early, style='Timing.TCheckbutton').pack(anchor='w', pady=(4, 22))
        self.control(panel, 'max_advance_ms', 'Maximum lead', 'Early slot filling never exceeds this lead time', 15000, background)
        tk.Label(panel, text='Early filling replaces faded rows individually; otherwise the screen/line advance option applies.', bg=background, fg='#999eaf', wraplength=570, justify='left').pack(anchor='w', pady=12)
        buttons = tk.Frame(panel, bg=background)
        buttons.pack(fill='x', pady=10)
        ttk.Button(buttons, text='Restore illustrated defaults', command=self.defaults).pack(side='left')
        ttk.Button(buttons, text='Apply', command=self.apply).pack(side='right', padx=8)
        ttk.Button(buttons, text='Close', command=win.destroy).pack(side='right')

    def control(self, panel, name, label, hint, maximum, bg):
        tk.Label(panel, text=label, bg=bg, fg='#e0e1ea', font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        row = tk.Frame(panel, bg=bg)
        row.pack(fill='x', pady=(14, 8))
        value = self.owner.timing_vars[name]
        scale = tk.Scale(row, from_=0, to=max(maximum, int(value.get())), orient='horizontal', showvalue=False, bg=bg, fg='#e0e1ea', troughcolor='#252838', activebackground='#8b80ff', highlightthickness=0, sliderrelief='flat', sliderlength=22, width=10, command=lambda v: value.set(str(round(float(v)))))
        scale.set(int(value.get()))
        scale.pack(side='left', fill='x', expand=True, padx=(0, 20))
        tk.Entry(row, textvariable=value, width=8, justify='right', bg='#171925', fg='#e0e1ea', insertbackground='white', relief='flat', font=('Consolas', 14)).pack(side='left', ipady=10)
        tk.Label(row, text='ms', bg=bg, fg='#999eaf', font=('Segoe UI', 12)).pack(side='left', padx=(4, 0))

        def sync(*args):
            try:
                number = int(value.get())
                if 0 <= number <= 60000 and round(scale.get()) != number:
                    scale.configure(to=max(maximum, number))
                    scale.set(number)
            except (ValueError, tk.TclError):
                pass
        trace_id = value.trace_add('write', sync)

        def cleanup(event):
            try:
                value.trace_remove('write', trace_id)
            except tk.TclError:
                pass
        scale.bind('<Destroy>', cleanup)
        if hint:
            tk.Label(panel, text=hint, bg=bg, fg='#999eaf', wraplength=560, justify='left').pack(anchor='w')
        tk.Frame(panel, bg=bg, height=22).pack()

    def defaults(self):
        self.owner.timing_enabled.set(True)
        self.owner.fill_early.set(True)
        for name, value in dict(advance_ms=4000, hold_ms=2000, fade_in_ms=200, fade_out_ms=200, max_advance_ms=6000).items():
            self.owner.timing_vars[name].set(str(value))

    def apply(self):
        if self.owner.apply():
            self.owner.status.set('Visibility timing applied to preview and subsequent video exports.')
