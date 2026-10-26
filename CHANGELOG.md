# Openjs-wx CHANGELOG: 0.8 → 0.15

This compares the final capabilities of 0.8 and 0.15 directly, without listing intermediate releases. The baseline was checked against the original 0.8 portable archive; current behavior was checked against the 0.15 source, documentation and verification results.

## Added and improved

### Project persistence

- Added a Project menu for opening, saving and saving copies of editing sessions.
- **Reference projects (`.opw`)** embed lyrics and settings and store paths to video/images, audio, all MIDI files and fonts.
- **Packed projects (`.opx`)** include every linked resource for transfer to another computer. Media files are copied without transcoding.
- Projects restore character timing, original lyrics and filtering options, MIDI track routing, playback mode, levels, audio/MIDI offsets, subtitle styles, preview/export settings and playback positions. Opening stays paused.
- Added missing-resource relocation, packed-resource integrity checks and persistent cache reuse. Both language editions share the same project format. Legacy `.mi3proj` / `.mi3pack` files remain readable.
- Added `Ctrl+O` to open, `Ctrl+S` to save, `Ctrl+Shift+S` to save a packed copy, and the `--project` command-line option.

### Flexible music and audio inputs

- The music input accepts MI3 or standard MIDI. Audio now accepts SD3, WAV, AAC, MP3, FLAC, APE and ALAC, including AAC/ALAC in `.m4a` containers.
- Music and audio need not share a name. MI3/MIDI can be paired with SD3 or external audio; multiple SMF files can share the selected audio source.
- External audio is decoded by content and converted to 44.1 kHz stereo float32 PCM, with resampling for other sample rates and channel layouts.
- Added audio-only sessions and improved MIDI-only loading, preview and video export, without requiring both input types.
- Extended audio offset from ±10 seconds to **±24 hours**, accepting fractional milliseconds. Positive values delay audio; negative values advance it and trim content before zero. Playback and mixed-audio export use the same offset. MIDI offset remains ±10 seconds.
- When following the player, the default export duration retains the tail of delayed audio.

### Lyric interchange and ASS sentence reconstruction

- Added embedded MIDI/XF lyrics, including XF02, XFKM and tempo-aware lyric timing.
- Added or expanded **XF, SRT, VTT, ASS, SSA, TTML, DFXP and SCC** import/export, while retaining JSON, CSV and LRC workflows.
- Added support for VTT inline timestamps, ASS karaoke syllables and TTML nested timing/spans. Character timing is retained within each format's limits.
- Fixed positioned ASS karaoke being interpreted as one sentence per character. Fragments sharing the display interval, style, layer, voice and baseline are joined in horizontal order, with remapped character indices and preserved waits, pauses and syllable timing.
- The actual `karaoke.ass` sample reconstructs **254 events into 66 sentences, retaining 351 timing spans**. Different baselines, layers or styles remain separate; ordinary unpositioned subtitles are not automatically joined.

### Live lyric editing from previews

- Added an editor entry point in video and green-screen previews through `F2` and the context menu. Previews of the same song share the current live editor.
- Add, delete or change lyric lines during playback, updating previews and subsequent exports.
- Added automatic line submission and application after approximately 350 ms of idle typing. Invalid drafts remain available for correction.
- Text edits retain timing for unchanged characters using text differences. Inserted/replaced characters remain untimed rather than receiving invented source timing.
- Added batch start/end/move nudges for timed characters, with steps starting at **1 ms**. Direct entry, dragging, timing marks and undo/redo remain available.
- Added current-line selection and a toggle for green-screen controls. Stale editors cannot overwrite the lyrics of a newly loaded song.

### Subtitle visibility and transitions

- Added optional advance display, post-sing hold, fade-in and fade-out settings.
- Added early filling of an available subtitle position and a maximum advance setting.
- These work with the existing page-change/immediate-line-change options. Font, size, colors, outline and background remain independently configurable.

### Language editions and portable runtime

- Updated both interface languages and documentation. Lyrics and filenames retain their original language.
- Bundled the additional caption dependencies for offline use of the new interchange and project features.
- Both 0.15 editions passed **99 automated tests**, with extracted portable-runtime checks for project save/restore, packed projects after original media removal, and the actual ASS sample.

## Existing in 0.8 and retained in 0.15

The following are retained capabilities rather than new additions: native MI3/SD3 decoding and synchronized playback, four MIDI outputs, multiple SMF files and per-track routing, firmware-derived character timing templates, left-to-right highlighting, the character timeline, optional four-digit bracket-marker filtering, video/still-image backgrounds, independent green-screen previews, MP4 and transparent Alpha ProRes 4444 MOV export, and Chinese/English portable editions.

## Upgrade notes

- Re-import the original ASS if an older project already contains its fragments as separate lyric lines.
- Reference projects require their source assets. Use packed projects for transfer. External MIDI synthesizers, drivers and recordings of their sound are not included.
- Subtitle interchange is not universally lossless: SRT drops character timing; SCC does not cover full Chinese/Japanese character sets; complex ASS placement, animation and font styling are not fully reproduced.
- Raw headerless `.pcm`, SMF type 2 and SMPTE time division remain unsupported. The APE decoder is bundled, but end-to-end playback verification has not covered a real APE sample.

See [Projects](PROJECTS.md), [Lyric formats and compatibility](SUBTITLE_FORMATS.md) and [Usage](README.md) for details.
