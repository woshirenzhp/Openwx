"""Integration tests: real song decode, deterministic audio, MIDI chase and GUI wiring."""
import hashlib
import queue
import threading
import time
import tkinter as tk
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
import bootstrap
import numpy as np
from song import load_song, read_mi3, restore_ca02, resources, TempoMap, RATE, MidiEvent
from engine import PlayerEngine, Settings, mix_block
ROOT = Path(__file__).resolve().parent.parent

def eventually(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError('Timed out waiting for playback worker')

class FakeMidi:

    def __init__(self, device):
        self.sent = []
        self.closed = False

    def send(self, data):
        self.sent.append(data)

    def panic(self):
        self.sent.append(b'PANIC')

    def collect(self):
        pass

    def close(self):
        self.closed = True

class FakeStream:

    def __init__(self, **kwargs):
        self.callback = kwargs['callback']
        self.active = False

    def start(self):
        self.active = True

    def abort(self):
        self.active = False

    def close(self):
        self.active = False

class PlayerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.song = load_song(ROOT / 'CE000001.MI3', ROOT / 'CE000001.SD3')

    def test_real_decoders_and_variant_association(self):
        song = self.song
        self.assertEqual([v.selected for v in song.variants], [[0, 1], []])
        self.assertEqual([v.note_count for v in song.variants], [330, 6509])
        self.assertEqual([len(p) for p in song.pcm], [8726528, 8638464])
        self.assertEqual(song.variants[0].starts, {0: 0, 1: 0})
        raw = (ROOT / 'CE000001.SD3').read_bytes()
        for i, ca in enumerate(resources(resources(raw)[0])):
            expected = (ROOT / 'sd3_analysis' / 'AAC' / f'CE000001_{i:02d}.aac').read_bytes()
            self.assertEqual(hashlib.sha256(restore_ca02(ca)).digest(), hashlib.sha256(expected).digest())
        self.assertEqual([len(d) for d in read_mi3(ROOT / 'CE000001.MI3')], [7394, 117927])

    def test_tempo_changes_and_note_off_mapping(self):
        tempo = TempoMap(120000, 48, [(48, 60000)])
        self.assertAlmostEqual(tempo.seconds_at(48), 0.5)
        self.assertAlmostEqual(tempo.seconds_at(96), 1.5)
        self.assertAlmostEqual(tempo.seconds_at(144), 2.5)

    def test_chunk_rendering_offset_and_gain(self):
        rng = np.random.default_rng(1)
        pcm = rng.uniform(-0.2, 0.2, size=(2000, 2)).astype('float32')
        song = SimpleNamespace(pcm=[pcm, pcm * 0.5])
        variant = SimpleNamespace(starts={0: 0, 1: 0})
        settings = Settings(audio_offset=5 / RATE, master=0.5, gains=[0.5, 1.0])
        full = mix_block(song, variant, [0, 1], 0, 2100, settings)
        pieces = np.concatenate([mix_block(song, variant, [0, 1], p, min(512, 2100 - p), settings) for p in range(0, 2100, 512)])
        np.testing.assert_array_equal(full, pieces)
        np.testing.assert_array_equal(full[:5], 0)
        np.testing.assert_allclose(full[5:2005], pcm * 0.5)
        np.testing.assert_array_equal(full[2005:], 0)

    def make_engine(self, clock=None):
        engine = PlayerEngine(FakeStream, FakeMidi, clock or time.perf_counter)
        self.addCleanup(engine.close)
        return engine

    def test_auto_mode_does_not_double_midi_variant(self):
        engine = self.make_engine()
        engine.configure(self.song, 0, Settings(midi_devices=(0, None)))
        eventually(lambda: engine.stream is not None)
        self.assertEqual(engine.tracks, [0, 1])
        engine.configure(self.song, 1, Settings(midi_devices=(0, None)))
        eventually(lambda: engine.variant.index == 1 and engine.stream is not None)
        self.assertEqual(engine.tracks, [])

    def test_dac_clock_pause_seek_and_no_early_midi(self):
        now = [100.0]
        engine = self.make_engine(lambda: now[0])
        variant = SimpleNamespace(selected=[0], starts={0: 0}, segmented=False, duration=2.0, events=[MidiEvent(0, 0, b'\x90<@'), MidiEvent(1, 0, b'\x80<\x00')])
        song = SimpleNamespace(variants=[variant], pcm=[np.ones((RATE * 2, 2), dtype='float32') * 0.2])
        engine.configure(song, 0, Settings(midi_devices=(0, None), gains=[1], master=1))
        eventually(lambda: engine.stream is not None)
        engine.command('play')
        eventually(lambda: engine.playing)
        out = np.empty((512, 2), dtype='float32')
        engine._callback(out, 512, SimpleNamespace(outputBufferDacTime=100.1, currentTime=100), None)
        time.sleep(0.02)
        self.assertNotIn(b'\x90<@', engine.outputs[0].sent)
        now[0] = 100.15
        eventually(lambda: b'\x90<@' in engine.outputs[0].sent)
        self.assertAlmostEqual(engine.position(), 0.05, places=5)
        engine.command('pause')
        eventually(lambda: not engine.playing)
        pos = engine.position()
        now[0] += 10
        self.assertAlmostEqual(engine.position(), pos)
        engine.command('seek', 1.5)
        eventually(lambda: abs(engine.position() - 1.5) < 0.0001)
        engine.command('play')
        eventually(lambda: engine.playing)
        sent = engine.outputs[0].sent
        self.assertEqual(sent.count(b'\x90<@'), 1)
        engine.command('stop')
        eventually(lambda: not engine.playing and engine.frame == 0)

    def test_seek_chases_sustained_notes(self):
        engine = self.make_engine()
        engine.outputs[0] = FakeMidi(0)
        engine.variant = SimpleNamespace(events=[MidiEvent(0, 0, b'\xc0\x05'), MidiEvent(0.1, 0, b'\xb0@\x7f'), MidiEvent(0.2, 0, b'\x90<P'), MidiEvent(0.3, 0, b'\x80<\x00'), MidiEvent(1, 0, b'\xb0@\x00')])
        engine.times = [e.time for e in engine.variant.events]
        engine._chase(0.5)
        self.assertIn(b'\x90<P', engine.outputs[0].sent)
        self.assertIn(b'\x80<\x00', engine.outputs[0].sent)
        engine.outputs[0].sent.clear()
        engine._chase(1.5)
        self.assertNotIn(b'\x90<P', engine.outputs[0].sent)

    def test_four_outputs_route_messages_and_all_close(self):
        engine = self.make_engine()
        engine.configure(self.song, 0, Settings(midi_devices=(0, 1, 2, 3)))
        eventually(lambda: len(engine.outputs) == 4 and engine.stream is not None)
        outputs = dict(engine.outputs)
        a = b'\x90<@'
        b = b'\x91>P'
        sysex = bytes.fromhex('f0411042124000046e4ef7')
        engine._send(MidiEvent(0, 0, a))
        engine._send(MidiEvent(0, 1, b))
        engine._send(MidiEvent(0, 0, sysex))
        for port in (0, 2):
            self.assertEqual(outputs[port].sent, [a, sysex])
        for port in (1, 3):
            self.assertEqual(outputs[port].sent, [b])
        engine.command('pause')
        eventually(lambda: all((b'PANIC' in o.sent for o in outputs.values())))
        engine.close()
        self.assertTrue(all((o.closed for o in outputs.values())))

    def test_duplicate_devices_rejected_across_all_four_ports(self):
        engine = self.make_engine()
        for selected in ((0, 1, 0, None), (0, 1, 2, 2)):
            with self.subTest(selected=selected):
                with self.assertRaisesRegex(ValueError, 'different devices'):
                    engine._configure(self.song, 0, Settings(midi_devices=selected))

    def test_four_outputs_can_all_follow_source_a(self):
        engine = self.make_engine()
        engine.configure(self.song, 0, Settings(midi_devices=(0, 1, 2, 3), midi_sources=(0, 0, 0, 0)))
        eventually(lambda: len(engine.outputs) == 4 and engine.stream is not None)
        note = b'\x90<@'
        engine._send(MidiEvent(0, 0, note))
        self.assertTrue(all((o.sent == [note] for o in engine.outputs.values())))
        engine._send(MidiEvent(0, 1, b'\x91<@'))
        self.assertTrue(all((o.sent == [note] for o in engine.outputs.values())))

    def test_gui_load_controls_and_variant_switch(self):
        from app import App
        root = tk.Tk()
        root.withdraw()
        engine = self.make_engine()
        app = App(root, engine=engine)
        try:
            app.on_loaded(self.song)
            end = time.monotonic() + 3
            while not app.ready and time.monotonic() < end:
                root.update()
                time.sleep(0.01)
            self.assertTrue(app.ready)
            self.assertEqual(len(app.variant_box['values']), 2)
            self.assertEqual(len(app.gain_vars), 2)
            self.assertEqual(len(app.midi_boxes), 4)
            self.assertEqual(tuple((v.get() for v in app.midi_source_vars)), ('Source A', 'Source B', 'Source A', 'Source B'))
            self.assertEqual(engine.tracks, [0, 1])
            app.variant_box.current(1)
            app.apply()
            eventually(lambda: engine.variant.index == 1)
            self.assertEqual(engine.tracks, [])
            root.update_idletasks()
            self.assertEqual(root.minsize(), (900, 850))
            self.assertGreater(app.log.winfo_reqheight(), 50)
        finally:
            app.closed = True
            root.destroy()

    def test_ce053877_parts_and_arbitrary_routes(self):
        song = load_song(ROOT / 'CE053877.MI3')
        self.assertEqual([v.note_count for v in song.variants], [364, 11926])
        variant = song.variants[1]
        self.assertEqual(len(variant.parts), 15)
        self.assertEqual([p.id for p in variant.parts if p.channels != 'SysEx'], list(range(14)))
        self.assertEqual(variant.parts[0].channels, '10')
        routes = {p.id: () for p in variant.parts}
        routes.update({0: (2,), 1: (0, 3), 16: (0, 2, 3)})
        engine = self.make_engine()
        engine._configure(song, 1, Settings(mode='midi', midi_devices=(0, 1, 2, 3), track_routes=routes))
        for part, ports in [(0, {2}), (1, {0, 3}), (2, set())]:
            for output in engine.outputs.values():
                output.sent.clear()
            event = next((e for e in variant.events if e.track == part and e.data[0] >> 4 == 9))
            engine._send(event)
            self.assertEqual({p for p, o in engine.outputs.items() if o.sent}, ports)
        for output in engine.outputs.values():
            output.sent.clear()
        event = next((e for e in variant.events if e.shared and e.port == 0))
        copies = [e for e in variant.events if e.time == event.time and e.data == event.data and (e.track == event.track)]
        for copy in copies:
            engine._send(copy)
        for p, output in engine.outputs.items():
            self.assertEqual(output.sent.count(event.data), 1 if p in (0, 2, 3) else 0)

    def test_multiple_smf_tempo_tracks_and_running_status(self):
        import mido
        from smf import load_smf_song
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / 'first.mid'
            second = Path(folder) / 'second.mid'
            a = mido.MidiFile(type=1, ticks_per_beat=480)
            a.tracks.append(mido.MidiTrack([mido.MetaMessage('track_name', name='Tempo'), mido.MetaMessage('set_tempo', tempo=500000), mido.Message('sysex', data=(126, 127, 9, 1)), mido.MetaMessage('set_tempo', tempo=1000000, time=480), mido.MetaMessage('end_of_track', time=480)]))
            for name, start in [('Bass', 0), ('Lead', 480)]:
                a.tracks.append(mido.MidiTrack([mido.MetaMessage('track_name', name=name), mido.Message('note_on', channel=0, note=60, velocity=70, time=start), mido.Message('note_on', channel=0, note=60, velocity=0, time=960 - start)]))
            a.save(first)
            b = mido.MidiFile(type=0, ticks_per_beat=480)
            b.tracks.append(mido.MidiTrack([mido.MetaMessage('set_tempo', tempo=250000), mido.MetaMessage('midi_port', port=3), mido.Message('note_on', channel=1, note=64, velocity=80), mido.Message('note_off', channel=1, note=64, time=960)]))
            b.save(second)
            song = load_smf_song([first, second])
            v = song.variants[0]
            self.assertEqual(len(v.parts), 4)
            self.assertEqual(v.note_count, 3)
            self.assertEqual(v.label, 'SMF')
            self.assertAlmostEqual(v.duration, 1.5)
            self.assertAlmostEqual(next((e.time for e in v.events if e.track == 2 and e.data[2] == 70)), 0.5)
            self.assertAlmostEqual(next((e.time for e in v.events if e.track == 3 and e.data[0] >> 4 == 8)), 0.5)
            self.assertTrue(all((e.port == 3 for e in v.events if e.track == 3)))
            self.assertIn('Bass', v.parts[1].name)
            self.assertIn(bytes.fromhex('f07e7f0901f7'), [e.data for e in v.events])
            engine = self.make_engine()
            engine._configure(song, 0, Settings(mode='midi', midi_devices=(0, 1, 2, 3), track_routes={0: (0, 1), 1: (0,), 2: (1,), 3: (2, 3)}))
            engine._chase(0.75)
            self.assertIn(b'\x90<F', engine.outputs[0].sent)
            self.assertIn(b'\x90<F', engine.outputs[1].sent)
            self.assertNotIn(b'\x91@P', engine.outputs[2].sent)
            self.assertEqual(engine.outputs[0].sent.count(bytes.fromhex('f07e7f0901f7')), 1)
            bad = mido.MidiFile(type=2)
            bad.tracks.append(mido.MidiTrack())
            bad.save(Path(folder) / 'bad.mid')
            with self.assertRaisesRegex(ValueError, 'type 2'):
                load_smf_song([Path(folder) / 'bad.mid'])

    def test_track_chase_controller_state_uses_physical_outputs(self):
        engine = self.make_engine()
        engine.outputs = {i: FakeMidi(i) for i in range(2)}
        engine.settings.track_routes = {0: (0,), 1: (1,), 2: (0,)}
        engine.variant = SimpleNamespace(events=[MidiEvent(0, 0, b'\xb0@\x7f', track=2), MidiEvent(0.1, 0, b'\x90<P', track=0), MidiEvent(0.1, 0, b'\x90<`', track=1), MidiEvent(0.2, 0, b'\x80<\x00', track=0), MidiEvent(0.3, 0, b'\x80<\x00', track=1)])
        engine.times = [e.time for e in engine.variant.events]
        engine._chase(0.5)
        self.assertIn(b'\x90<P', engine.outputs[0].sent)
        self.assertIn(b'\x80<\x00', engine.outputs[0].sent)
        self.assertNotIn(b'\x90<`', engine.outputs[1].sent)

    def test_route_table_ce053877_variant_switch_and_mute(self):
        from app import App
        root = tk.Tk()
        root.withdraw()
        app = App(root, engine=self.make_engine())
        try:
            app.on_loaded(load_song(ROOT / 'CE053877.MI3'))
            self.assertEqual(app.variant_box.current(), 1)
            self.assertEqual(len(app.route_tree.get_children()), 15)
            app.route_tree.selection_set('0', '1')
            app.assign_routes((1, 3))
            app.apply()
            eventually(lambda: app.engine.settings.track_routes is not None and app.engine.settings.track_routes[0] == (1, 3))
            app.route_tree.selection_set('1')
            app.assign_routes(())
            app.variant_box.current(0)
            app.ensure_routes()
            app.variant_box.current(1)
            app.ensure_routes()
            self.assertEqual(app.route_maps[1][0], {1, 3})
            self.assertEqual(app.route_maps[1][1], set())
            self.assertEqual(app.route_tree.set('1', 'A'), '·')
        finally:
            app.closed = True
            root.destroy()

    def test_invalid_track_routing_rejected(self):
        song = load_song(ROOT / 'CE053877.MI3')
        engine = self.make_engine()
        with self.assertRaisesRegex(ValueError, 'missing'):
            engine._configure(song, 1, Settings(track_routes={999: (0,)}))
        with self.assertRaisesRegex(ValueError, 'A/B/C/D'):
            engine._configure(song, 1, Settings(track_routes={0: (4,)}))
if __name__ == '__main__':
    unittest.main(verbosity=2)
