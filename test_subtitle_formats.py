"""Standards-oriented fixtures and interchange integration, including MIDI/XF chunks."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import io
import struct
import tempfile
import tkinter as tk
import unittest
import mido
from lyrics import Cue, load, save_cues
from song import load_song
from subtitle_formats import read_blocks, read_ttml, IMPORT_PATTERN, EXPORT_TYPES

class SubtitleFormatTests(unittest.TestCase):

    def test_positioned_ass_syllables_join_by_baseline_and_keep_waits(self):
        from lyrics import ass
        header = '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        rows = ['Dialogue: 5,0:00:10.00,0:00:20.00,Main,,0,0,0,,{\\an2\\pos(200,900)}{\\k300\\kf50}B', 'Dialogue: 5,0:00:10.00,0:00:20.00,Main,,0,0,0,,{\\an2\\pos(100,900)}{\\k200}{\\kf50}A{\\k25}{\\kf25}a', 'Dialogue: 5,0:00:10.00,0:00:20.00,Main,,0,0,0,,{\\an2\\pos(100,950)}{\\k200\\kf50}Other', 'Dialogue: 6,0:00:10.00,0:00:20.00,Main,,0,0,0,,{\\an2\\pos(300,900)}{\\kf50}Layer', 'Dialogue: 5,0:00:10.00,0:00:20.00,Translation,,0,0,0,,{\\an2\\pos(400,900)}{\\kf50}Translation']
        result = ass(header + '\n'.join(rows))
        self.assertEqual([c.text for c in result], ['AaB', 'Other', 'Layer', 'Translation'])
        self.assertEqual(result[0].spans, [(2, 2.5, 0, 1), (2.75, 3, 1, 2), (3, 3.5, 2, 3)])
        self.assertEqual((result[0].start, result[0].end), (10, 20))

    def test_ass_keeps_ordinary_simultaneous_and_duplicate_position_events(self):
        from lyrics import ass
        header = '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        rows = ['Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\kf100}A', 'Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\kf100}B']
        self.assertEqual(len(ass(header + '\n'.join(rows))), 2)
        rows = [row.replace('{\\kf100}', '{\\pos(10,20)\\kf100}') for row in rows]
        self.assertEqual(len(ass(header + '\n'.join(rows))), 2)

    def test_actual_karaoke_ass_sentence_and_character_times(self):
        path = Path(__file__).resolve().parent.parent / 'sync_player/karaoke.ass'
        cues = load(path)
        self.assertEqual(len(cues), 66)
        self.assertEqual(sum((len(c.spans) for c in cues)), 351)
        self.assertEqual(len(cues[1].text), 9)
        self.assertEqual(len(cues[1].spans), 9)
        self.assertAlmostEqual(cues[1].start + cues[1].spans[0][0], 35.51)
        self.assertAlmostEqual(cues[1].spans[4][0] - cues[1].spans[3][1], 0.12)
        self.assertTrue(all((l < r for c in cues for a, b, l, r in c.spans)))
        with tempfile.TemporaryDirectory() as folder:
            for suffix in ('ass', 'ttml'):
                target = Path(folder) / ('sentences.' + suffix)
                save_cues(target, cues)
                restored = load(target)
                self.assertEqual([c.text for c in restored], [c.text for c in cues])
                for original, actual in zip(cues, restored):
                    for expected, span in zip(original.spans, actual.spans):
                        self.assertEqual(expected[2:], span[2:])
                        self.assertAlmostEqual(expected[0], span[0])
                        self.assertAlmostEqual(expected[1], span[1])

    def test_all_requested_formats_roundtrip_and_unicode(self):
        with tempfile.TemporaryDirectory() as folder:
            for ext in ('xf', 'srt', 'vtt', 'ass', 'ssa', 'ttml', 'dfxp', 'scc'):
                with self.subTest(format=ext):
                    body = 'Hello world' if ext == 'scc' else '你好 world'
                    cues = [Cue(2, 4, body, [(0, 1, 0, 3), (1, 2, 3, len(body))])]
                    path = Path(folder) / ('captions.' + ext)
                    save_cues(path, cues)
                    result = load(path)
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].text, body)
                    tolerance = 0.035 if ext == 'scc' else 0.002
                    self.assertAlmostEqual(result[0].start, 2, delta=tolerance)
                    self.assertAlmostEqual(result[0].end, 4, delta=tolerance)
                    if ext in ('xf', 'vtt', 'ass', 'ssa', 'ttml', 'dfxp'):
                        self.assertEqual(result[0].spans, cues[0].spans)

    def test_ttml_nested_offsets_ticks_and_line_breaks(self):
        text = '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttp="http://www.w3.org/ns/ttml#parameter" ttp:tickRate="100">\n        <body begin="1s"><div begin="2s"><p begin="500ms" dur="3s"><span begin="50t" dur="1s">Hello</span><br/><span begin="150t" end="250t">World</span></p></div></body></tt>'
        cue = read_ttml(text)[0]
        self.assertEqual((cue.start, cue.end, cue.text), (3.5, 6.5, 'Hello\nWorld'))
        self.assertEqual(cue.spans, [(0.5, 1.5, 0, 5), (1.5, 2.5, 6, 11)])

    def test_ttml_sequential_container_and_frame_clock(self):
        text = '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttp="http://www.w3.org/ns/ttml#parameter" ttp:frameRate="25"><body><div timeContainer="seq"><p dur="25f">One</p><p begin="00:00:00:10" dur="1s">Two</p></div></body></tt>'
        cues = read_ttml(text)
        self.assertEqual([(c.start, c.end, c.text) for c in cues], [(0, 1, 'One'), (1.4, 2.4, 'Two')])

    def test_ttml_dfxp_span_gaps_and_multiline_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            for ext in ('ttml', 'dfxp', 'ass'):
                original = Cue(1, 5, 'A\nB', [(0.2, 1, 0, 1), (2, 3, 2, 3)])
                path = Path(folder) / ('gaps.' + ext)
                save_cues(path, [original])
                actual = load(path)[0]
                self.assertEqual(actual.text, original.text)
                self.assertEqual(actual.spans, original.spans)

    def test_srt_vtt_entities_identifiers_settings_and_inline_times(self):
        cues = read_blocks('1\n00:00:01,250 --> 00:00:03,500\n<b>A &amp; B</b>\nsecond line\n')
        self.assertEqual((cues[0].start, cues[0].end, cues[0].text), (1.25, 3.5, 'A & B\nsecond line'))
        text = 'WEBVTT\n\nNOTE hidden\nignore me\n\nid-1\n00:01.000 --> 00:03.000 align:start\n<v Alice><b>A</b><00:02.000>B</v>\n'
        cue = read_blocks(text, True)[0]
        self.assertEqual(cue.text, 'AB')
        self.assertEqual(cue.spans, [(0, 1, 0, 1), (1, 2, 1, 2)])

    def test_xf_tempo_offset_japanese_and_xf_chunk_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'embedded.mid'
            midi = mido.MidiFile(type=1, charset='latin1')
            midi.tracks.append(mido.MidiTrack([mido.MetaMessage('set_tempo', tempo=500000), mido.MetaMessage('set_tempo', tempo=1000000, time=480), mido.MetaMessage('end_of_track', time=720)]))
            text = mido.MidiTrack([mido.MetaMessage('cue_marker', text='$Lyrc:1:240:JP'), mido.MetaMessage('lyrics', text='こ'.encode('shift_jis').decode('latin1'), time=480), mido.MetaMessage('lyrics', text='え'.encode('shift_jis').decode('latin1'), time=480), mido.MetaMessage('lyrics', text='/', time=240)])
            midi.tracks.append(text)
            midi.save(path)
            cue = load(path)[0]
            self.assertEqual((cue.start, cue.end, cue.text), (0.25, 1.5, 'こえ'))
            self.assertEqual(cue.spans, [(0, 0.75, 0, 1), (0.75, 1.25, 1, 2)])
            extra = mido.MidiFile(type=0)
            extra.tracks.append(mido.MidiTrack([mido.MetaMessage('cue_marker', text='$Lyrc:1:0:L1'), mido.MetaMessage('lyrics', text='Other', time=480), mido.MetaMessage('lyrics', text='/', time=480)]))
            buffer = io.BytesIO()
            extra.save(file=buffer)
            chunk = buffer.getvalue()[22:]
            with path.open('ab') as out:
                out.write(b'XFKM' + struct.pack('>I', len(chunk)) + chunk)
            self.assertEqual(load(path)[0].text, 'Other')

    def test_xf_export_version_and_literal_control_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lyrics.xf'
            text = 'A / ^ % < [0125] \\ B'
            save_cues(path, [Cue(1, 3, text)])
            midi = mido.MidiFile(path)
            self.assertEqual(midi.type, 0)
            version = next((msg for msg in midi.tracks[0] if msg.type == 'sequencer_specific'))
            self.assertEqual(bytes(version.data), bytes.fromhex('43 7b 00 58 46 30 32 00 10'))
            self.assertEqual(load(path)[0].text, text)

    def test_xf_unicode_bom_and_line_break_gaps(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'unicode.xf'
            body = 'A\n你好🌟'
            save_cues(path, [Cue(2, 5, body, [(0, 1, 0, 1), (1, 3, 2, len(body))])])
            self.assertEqual(load(path)[0].text, body.replace('\n', ' '))
            self.assertIn(b'\xff\xfe', path.read_bytes())

    def test_vtt_keeps_syllable_end_before_a_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'pause.vtt'
            original = Cue(1, 5, 'AB', [(0.2, 1, 0, 1), (2, 3, 1, 2)])
            save_cues(path, [original])
            actual = load(path)[0]
            self.assertEqual(actual.text, original.text)
            for expected, span in zip(original.spans, actual.spans):
                self.assertAlmostEqual(expected[0], span[0])
                self.assertAlmostEqual(expected[1], span[1])

    def test_json_span_lists_export_to_xf_without_losing_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / 'edit.json'
            target = Path(folder) / 'edit.xf'
            save_cues(original, [Cue(2, 5, 'A\nB!', [(0, 1, 0, 1), (1, 2, 2, 3)])])
            save_cues(target, load(original))
            self.assertEqual(load(target)[0].text, 'A B!')

    def test_precision_limits_are_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            cue = Cue(0.0011, 0.0012, 'brief')
            for suffix in ('srt', 'vtt', 'ass', 'ssa'):
                with self.assertRaises(ValueError):
                    save_cues(Path(folder) / ('brief.' + suffix), [cue])
            target = Path(folder) / 'brief.ttml'
            save_cues(target, [cue])
            actual = load(target)[0]
            self.assertEqual((actual.start, actual.end), (0.0011, 0.0012))

    def test_lyric_export_refuses_current_source_paths(self):
        from lyrics import protect_source
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'original.mid'
            save_cues(path, [Cue(1, 3, 'Original')])
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                protect_source(path, SimpleNamespace(mi3=path, sd3=None))
            self.assertEqual(path.read_bytes(), original)

    def test_xf_lyric_only_file_loads_as_song_and_auto_populates_gui(self):
        from app import App
        from engine import PlayerEngine
        from test_player import FakeStream, FakeMidi
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lyrics.mid'
            save_cues(path, [Cue(2, 4, 'Syllable')])
            song = load_song(path)
            self.assertEqual(song.lyric_cues[0].text, 'Syllable')
            self.assertEqual(song.variants[0].duration, 4)
            root = tk.Tk()
            root.withdraw()
            player = App(root, engine=PlayerEngine(stream_factory=FakeStream, midi_factory=FakeMidi))
            try:
                player.on_loaded(song)
                player.open_presentation()
                self.assertEqual(player.presentation.cues[0].text, 'Syllable')
                target = Path(folder) / 'ui.srt'
                with patch('presentation.filedialog.asksaveasfilename', return_value=str(target)):
                    player.presentation.save_lyrics()
                self.assertEqual(load(target)[0].text, 'Syllable')
            finally:
                root.update_idletasks()
                for job in root.tk.call('after', 'info'):
                    root.after_cancel(job)
                player.close()

    def test_scc_exact_drop_frame_minutes_hours_and_odd_parity(self):
        from scc_lyrics import frame_number, timecode
        for frame in (0, 29, 1799, 1800, 17982, 107892, 2589407):
            self.assertEqual(frame_number(timecode(frame)), frame)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'late.scc'
            original = [Cue(62.3, 64.5, 'Caption one'), Cue(600.2, 603.4, 'Café & music')]
            save_cues(path, original)
            cues = load(path)
            self.assertEqual([c.text for c in cues], [c.text for c in original])
            for expected, actual in zip(original, cues):
                self.assertAlmostEqual(expected.start, actual.start, delta=0.018)
                self.assertAlmostEqual(expected.end, actual.end, delta=0.018)
            for line in path.read_text().splitlines():
                if '\t' in line:
                    for word in line.split('\t')[1].split():
                        for b in bytes.fromhex(word):
                            self.assertEqual(b.bit_count() % 2, 1)

    def test_scc_rejects_unicode_overlap_and_truncated_load_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.scc'
            for cues in ([Cue(1, 2, '中文')], [Cue(1, 3, 'A'), Cue(2, 4, 'B')], [Cue(0, 0.01, 'This cannot arrive in time')]):
                with self.assertRaises(ValueError):
                    save_cues(path, cues)
                self.assertFalse(path.exists())

    def test_invalid_times_and_filtering_all_export_formats(self):
        with tempfile.TemporaryDirectory() as folder:
            for suffix in ('.xf', '.srt', '.vtt', '.ass', '.ssa', '.ttml', '.dfxp', '.scc'):
                path = Path(folder) / ('filtered' + suffix)
                save_cues(path, [Cue(2, 4, '[0125]Hello')], True)
                self.assertEqual(load(path)[0].text, 'Hello')
                with self.assertRaises(ValueError):
                    save_cues(path, [Cue(float('nan'), 4, 'bad')])
        for suffix in ('xf', 'srt', 'vtt', 'ass', 'ssa', 'ttml', 'dfxp', 'scc'):
            self.assertIn('*.' + suffix, IMPORT_PATTERN)
            self.assertTrue(any(('*.' + suffix == pattern for name, pattern in EXPORT_TYPES)))
if __name__ == '__main__':
    unittest.main()
