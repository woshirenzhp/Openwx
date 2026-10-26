# Lyric formats and compatibility · Openjs-wx 0.12

Loading MIDI/XF music reads embedded lyrics automatically. Open **Video / Lyrics / Export...** to preview them, or use **Import lyrics / timing** for a separate subtitle file. **Export lyrics / subtitles...** and the character timeline's save dialog support all formats below. Audio-only and MIDI-only sessions are supported.

`subtitle_samples` contains equivalent English examples in all eight formats. These are lyric files without music or recordings.

| Format | Import / export | Timing and limits |
|---|---|---|
| XF / MIDI | FF05 lyrics, `$Lyrc`, XF02 and embedded XFKM; syllable highlighting | SMF type 0/1 with PPQN; tempo-aware tick offsets. Export is a lyric-only type 0 SMF at 120 BPM / 480 PPQN, approximately 1.04 ms per tick. Original accompaniment tracks are not copied. Use `.xf` or `.mid`. |
| SRT | Line start/end, plain text, line breaks | Millisecond precision; no syllable highlighting. |
| VTT | Line times, breaks, inline syllable timestamps | Millisecond precision; ordered syllables and pauses. Source positions, regions and styling are ignored. |
| ASS | Dialogue and `\k` / `\kf` / `\ko` / `\kt` timing | Centisecond precision; export uses `\kt` plus `\kf` for independent syllable starts and durations. Older software may not support `\kt`. |
| SSA | v4.00 Dialogue and `\k` | Centisecond precision; syllable durations become sequential, simplifying independent gaps. |
| TTML / DFXP | XML paragraph times, nested offsets, timed spans, br breaks | begin/end/dur, h/m/s/ms/f/t, frame/tick rates and finite seq containers. Export uses a basic media-time TTML subset, six decimal places for span times. Not a complete implementation of every TTML/IMSC broadcast profile. |
| SCC | CEA-608 pop-on export; library-supported roll-up/paint-on import | 29.97 fps; DF/NDF import, DF export, about 33.37 ms per frame. No syllable highlighting. |
| JSON / CSV | Independent display/sing/clear times, all spans and provenance | Recommended for a complete editable project. |

## XF

Embedded XFKM takes priority over MTrk lyric copies. The first lyric-bearing track is selected to avoid mixing translations. With multiple MIDI files, automatic lyrics come from the first file with valid lyrics.

Common XF controls and escaped punctuation are supported. Page/semantic breaks become ordinary cue boundaries; full device page layouts and every proprietary cue command are not emulated. Supported encodings are L1, JP, HZ, B5, CY, KR and BOM-marked Unicode. VN is not supported. Without a declaration, UTF-8, CP932 and Latin-1 are tried.

`$Lyrc` lead time is measured in MIDI ticks and converted through the tempo map. MIDI normally specifies syllable starts; the next syllable/break estimates the end. Without a final break, the song end is considered and the final syllable gets at least two seconds. These are inferred syllable ends, not native character-end timestamps.

XF export contains lyrics and clock only, without accompaniment. Hard line breaks inside a cue become spaces. A line ends by the next line's singing start, simplifying independent display/sing/clear timing. Unrepresentable overlaps or reversed syllables are rejected; use TTML or JSON instead. Traditional encodings are preferred when they cover all text; mixed text falls back to BOM-marked UTF-16. Hardware Unicode compatibility varies.

## SCC

CEA-608 cannot encode full Chinese/Japanese character sets. Unsupported characters cause an explicit export error rather than silent replacement with question marks; use SRT, VTT, ASS or TTML. Lines wrap at 32 characters, with a 15-row maximum. Single-channel export rejects overlaps. Very short or dense captions may exceed the one-codeword-per-frame transmission budget and are rejected.

Text must be preloaded before display. A first caption close to time zero appears after loading completes because transmission before zero is impossible. Normal captions use exact NTSC display/clear frames and drop-frame numbering across minute/hour boundaries. The first decoded caption group is selected; broadcast positioning/colors do not replace player styling.

## Saving

Text subtitle export uses the editable cue timeline without baking in the video's temporary lyric preview offset. Shift the timeline first if needed. The optional four-digit-bracket filter is applied when enabled. Export uses basic styles; fonts, animations, regions and complex source layouts are not guaranteed to round-trip. ASS/SSA literal braces become full-width characters to avoid being interpreted as overrides. Export cannot overwrite the currently loaded music or audio source.

pycaption 2.3.13 and its dependencies are bundled for offline use. SCC text coding/control decoding uses the library; an adapter schedules and reads exact NTSC frame times.

References: [Yamaha XF v2.01](https://musescore.org/sites/musescore.org/files/2023-09/xfspec.pdf), [Yamaha authoring guide](https://jp.yamaha.com/files/download/other_assets/8/321758/xfsongdata.pdf), [W3C TTML](https://www.w3.org/TR/ttml2/), [pycaption](https://github.com/pbs/pycaption).

## Positioned ASS karaoke (0.15)

For exporters that split a sentence across multiple Dialogue events, the importer joins karaoke fragments with the same display start/end, style, layer, voice and vertical position, ordered by horizontal position. Character indices are remapped while syllable times and empty karaoke waits are retained. Different baselines, layers or styles are kept separate; unpositioned events and duplicate positions are not joined. Fonts, absolute placement and animation continue to use player settings. Re-import the ASS file to replace lyrics already split in an older project.
