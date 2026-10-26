# MI3 + SD3 Sync Player

New in 0.15: .opw reference / .opx packed projects; positioned ASS karaoke syllables are reconstructed into complete sentences with their original timing. Legacy project files remain readable. See [Projects](PROJECTS.md).

New in 0.13: a live lyric editor accessible from preview windows, reversible line edits, preserved timing for unchanged text, and 1 ms character nudges.

## Edit lyrics while previewing

1. Click **Edit lyrics... F2** below the video preview, press F2 in either video/green-screen preview, or use its right-click menu. Multiple previews share the current live editor. Green-screen controls start hidden; F10 toggles the control bar.
2. **Auto-commit line input** and **Auto apply** start enabled. After a 350 ms typing pause, valid text and display/sing/clear times are committed without moving the text cursor, then applied to previews. Invalid drafts remain in the fields for correction. Disable auto-commit to use **Commit line** explicitly.
3. Add a line at the current playhead, delete selected lines, undo/redo, or delete everything and start again. **Find current lyric line** selects the active line; double-clicking a row or using the seek button moves playback. Editing does not stop preview playback.
4. Text-difference matching preserves unchanged characters' timing and remaps their indices. New/replaced characters remain untimed. Editing inside a multi-character syllable clears that syllable's timing rather than inventing character times; other complete syllables remain. Undo is available; split syllables explicitly before refining them.
5. Select one or more timed characters and set a **Character nudge step ms** (1–60000 ms). Nudge Start, End or Move with − / +, type times to 0.001 s, drag handles, or mark start with F7 and end/next with F8. New text can use an explicitly estimated equal-division draft before calibration. Character times must remain inside the line's display/clear interval.
6. Applied edits update every preview and subsequent video exports. Save JSON/CSV for complete character timing, or use the supported subtitle formats. The temporary video lyric offset is not baked into text subtitle exports. Live application does not automatically save a file; source songs remain unchanged.
7. Loading another song or replacing lyrics elsewhere protects the new lyrics from an older editor. F2 then opens a fresh current editor; the old draft can still be saved separately.

New in 0.12: embedded MIDI/XF lyrics and XF, SRT, VTT, ASS, SSA, TTML, DFXP and SCC import/export. See [Lyric formats and compatibility](SUBTITLE_FORMATS.md). Use the lyric import/export buttons or the character timeline. The bundled lyric-only XF example can be loaded in the main window.

**Openjs-wx 0.15 English edition — Windows 10/11, 64-bit**

## Audio-only / MIDI-only sessions and manual PCM offset

For audio only, leave the first input empty, select SD3 or supported audio in the second input, and click **Load files**. **Audio only** mode is selected automatically. For music only, select MI3 or MIDI and leave the audio input empty; **MIDI only** is selected automatically. Both sessions support playback and MP4 or transparent ProRes MOV video export without the other input. Audio-only sessions also look for matching LRC/ASS files; lyrics can be imported or edited separately.

Enter milliseconds in **Audio/PCM offset ms** and click **Apply settings (restart)**. Decimal values are accepted, within +/-86400000 ms (24 hours). Positive values add leading silence; negative values trim the beginning and advance the audio. Playback and **Current audio mix** video export share this offset. After applying settings, the default export duration updates when following the main player, retaining the delayed audio tail. MIDI offset remains limited to +/-10000 ms.

MIDI-only video export defaults to **No audio** and does not require SD3. MIDI playback uses the selected external ports; exported videos do not capture or synthesize that instrument's sound. Audio-only command line: `runtime\python.exe app.py --audio "D:\backing.flac"`.

## Freely paired music and audio inputs

The first input accepts MI3 or standard MIDI (`.mid`, `.midi`, or SMF-based `.kar`). Use the multiple-SMF button for simultaneous MIDI files, each retaining its tempo map and A/B/C/D routing. SMF types 0/1 with PPQN timing are supported; asynchronous type 2 and SMPTE timing are not supported.

The second input is optional and accepts SD3, WAV, AAC, MP3, FLAC, APE or ALAC. AAC and ALAC in `.m4a` containers are supported. Files need not share a name. Changing the music input keeps the selected audio. The first audio stream in a container is decoded.

External audio is decoded in memory to 44.1 kHz stereo float32 PCM and begins at song time zero. Other sample rates and channel layouts are resampled. Raw headerless `.pcm` files are not supported because sample rate and channel information is missing. Source files remain unchanged.

Auto mode preserves native MDT recording links and gates for MI3 + SD3. MI3 + external audio, MIDI + SD3 and MIDI + external audio play the complete audio timeline from zero, using the existing audio offset, gain, pause and seek controls. Multiple MIDI files share the audio selected in the second input.

Choose **Current audio mix** to include this audio in video export with the same offset and gain. External MIDI synthesizer sound is not captured or synthesized into the exported audio.

The entire audio is decoded into memory, using approximately 20.2 MiB per minute. The bundled runtime includes the APE decoder. Real encode/decode regression tests cover WAV, AAC, MP3, FLAC and ALAC; no real APE sample was available for an end-to-end test.

Command-line aliases: `runtime\python.exe app.py --music "D:\song.mid" --audio "D:\backing.flac"`. The original `--mi3` and `--sd3` arguments remain valid.

This is a separate English edition of version 0.15. The interface, dialogs, status messages, error messages and documentation are in English. Song titles, track names and lyric content retain their original language. Playback and file formats are unchanged.

## Start the portable player

1. Extract **all** files from `MI3_SD3_Sync_Player_Portable_Openjs-wx_0.15_EN.zip`.
2. Open the `MI3_SD3_Player_EN` folder.
3. Double-click `start_player.cmd`.

Do not run the launcher from inside the ZIP. Keep the `runtime` and `fonts` folders alongside the application. Python and the required dependencies are bundled; installation and an Internet connection are not required.

Songs are not included. `start_sample.cmd` looks for `CE000001.MI3` and `CE000001.SD3` beside the launcher, then in its parent folder. It loads the files without starting playback.

## Load and play a song

1. Browse for MI3 or MIDI and optionally select SD3 or external audio. An empty audio field can be filled automatically with a same-named SD3.
2. Click **Load files** and wait for decoding to finish.
3. Select a **Music resource** and **Playback mode**.
4. Choose an **Audio output** and, when needed, MIDI output devices.
5. Apply settings, then click **Play**.

Available playback modes:

| Mode | Behavior |
|---|---|
| Auto: native links / full external audio | Native MI3 + SD3 follows MDT links; arbitrary pairs use the complete audio |
| Manual: all audio + MIDI | Mixes the available audio with MIDI |
| Audio only | Plays the audio without MIDI |
| MIDI only | Sends MIDI without audio |

Changing devices, offsets or track routing requires **Apply settings (restart)**, which resets playback position. Audio master and individual audio-track levels take effect immediately. They do not control external MIDI synthesizer volume.

Audio and MIDI offsets are in milliseconds. Positive values delay that output; negative values advance it. Audio accepts +/-86400000 ms (24 hours); MIDI accepts +/-10000 ms. Data before the song's starting position is trimmed when a negative offset is used.

Pause, stop and seek release active notes. Resuming reconstructs controller state and notes that should still be sounding. Original device sounds, proprietary controls, mixing and hardware latency are not fully reproduced.

## Four MIDI outputs and per-track routing

The player supports up to four distinct Windows WinMM MIDI devices, labeled **A**, **B**, **C** and **D**. Select different devices for enabled outputs. If you use a single synthesizer, enable only one output.

Click A/B/C/D cells in the routing table to toggle a track's destinations. A track can send to multiple outputs. Turn all destinations off to mute MIDI from that track. Select multiple rows to apply routing or mute changes together.

**Source A/B** are logical source assignments used by **Use default sources**. The routing table determines the actual destination devices. Tracks sharing an output port and MIDI channel also share program and controller state; route them to separate ports if independent sounds are required.

MIDI is sent to external or software synthesizers. Choosing no MIDI output tracks events silently; the player does not contain a replacement for the original hardware sound generator.

## Load multiple standard MIDI files

Click **Load SMF files...** and use Ctrl/Shift to select `.mid` or `.midi` files. This replaces the current music session and uses the SD3 or external audio selected in the second input. With audio, Auto mode is selected; without audio, MIDI-only playback is selected.

SMF type 0 and type 1 are supported. Each file keeps its own tempo map and all files start at the same time. Their song lengths are not automatically aligned. Every SMF track is retained, including setup/tempo tracks. Channels within a type-0 track are not automatically split into separate tracks. Type 2 and SMPTE time division are not supported.

To return to MI3/SD3 playback, load the corresponding MI3 and SD3 again.

## Video, still images and lyric previews

Open **Video / Lyrics / Export...**.

- Choose a video or still image as the background. A still image can remain on screen for the entire exported video.
- Import timed lyrics or load them from MI3.
- Select a font file, font size, text/highlight/stroke colors, stroke width and bottom margin.
- Use **Apply style and offsets** after editing numeric settings. Color selection applies immediately.
- Open the **Video / image preview** or **Green-screen lyrics** window. F11 toggles fullscreen; Esc exits fullscreen.

**Follow main player clock** synchronizes previews with song playback. With no song loaded, the presentation can run on its own clock. Lyric and video offsets are independent and accept +/-60000 ms. A positive lyric offset delays the lyrics.

Preview and export have separate switches. Enabling preview does not create a video file. Input-video sound is available for export; live preview uses the main player audio rather than a separate video-audio player.

The default lyric font is `fonts/UDRGMZtk.ttf`, extracted unchanged from the user-provided `FONTS.CAB` (KAGA-UD Maru Gothic / SUDRGKG-HW-MZ). You can choose another installed or local TTF/TTC/OTF file. The font need not be installed system-wide.

### Line advance options

**Lines per screen** selects 1–4 displayed rows. The player reduces this if necessary to fit the chosen font and bottom margin. Long text wraps according to actual font width; wrapped rows count toward the screen limit.

**Advance after each line** is off by default:

| Setting | Behavior |
|---|---|
| Off | Completed lines remain in place. The entire screen changes once every displayed row has finished highlighting and the next screen is due. |
| On | Once the top row's last character has fully highlighted, that row is removed, other rows move up and the next row appears. |

For wrapped text, completion is calculated from the character indices belonging to each displayed row. Changing the checkbox applies immediately, including while paused. The audio and character timestamps are not shifted. If the following lyrics are already in progress when displayed, their color reflects the current song time.

In immediate mode the last row clears when it finishes. Without character timing, a line uses its end time to advance. In whole-screen mode a timed line can remain visible past its original clear time while waiting for the other rows or the next screen.

### Optional numeric-marker filtering

**Filter [4-digit codes]** is off by default. When enabled, preview and exports remove bracketed strings containing exactly four ASCII digits, such as `[0125]`, `[1234]` or `[0000]`.

`[123]`, `[12345]`, `[AB12]`, full-width digits and time tags such as `[01:25.00]` are not removed. The source file and editor text are retained. Turning filtering off restores the original text. Character indices are remapped without shifting the remaining timestamps.

Saving lyric files or exporting timing templates uses the current filter setting. The timeline editor deliberately shows the original text so that character indexing stays stable.

## Default MI3 character templates

MI3 loading generates an editable character timing template automatically. The same timing is used for previews and video export.

Verified SNG line times and color-speed events determine a cumulative sweep curve. That curve is normalized to substitute font character widths, and character boundaries are estimated from it. Zero-speed trailing holds are not distributed over the sung text. A line without usable speed data falls back to a width-proportional estimate.

**These are estimates, not recovered original per-character timestamps.** The navigation font is not proven to have the same geometry as the MIPS device's `FONTxx.BIN` bitmap fonts. Original ruby annotation layout and all custom glyph mappings are not reproduced. The editor labels these entries **Estimated template; editable**.

Each character colors linearly from left to right between its own start and end times. Stroke color remains unchanged. The character remains highlighted after completion. This effect is shared by previews, MP4 and transparent MOV. Output frame rate and pixel resolution limit the apparent motion precision.

## Edit line and character timing

Click **Character timeline...**. Edits do not modify the source MI3.

- Select a line and edit its text, display time, highlight-start time or clear time. Click **Commit line**.
- Drag line handles or whole bars on the **Line timeline**. Select several rows to shift them together.
- On the **Character timeline**, select a character, enter its start/end times and click **Commit character**.
- Use the live playback clock to record timing marks.
- Undo/redo is available. **Apply to preview** updates subsequent previews and exports. **Auto apply** applies edits automatically.

| Key | Action |
|---|---|
| F4 | Mark line display time |
| F5 | Mark line highlight-start time |
| F6 | Mark line clear time |
| F7 | Mark character start |
| F8 | Mark character end and select the next character |

Time input accepts seconds, `mm:ss.sss` or `hh:mm:ss.sss`, with 0.001-second input precision. Original MI3 line/control times have 0.01-second resolution; finer editor input does not increase the precision of the source data.

**Split segments** divides an existing timed segment evenly into characters. **Even draft** generates a draft across the line's highlight interval. Both are explicitly estimated starting points for manual adjustment.

Editing a line's text resets its character timing; undo can restore it. If another window replaces the main player's lyrics, an older timeline is prevented from applying over them. It can still save its draft.

### Saving and importing

| Format | Preserved information |
|---|---|
| JSON | Line display/highlight/clear times, character spans and timing provenance |
| CSV | The same complete timing, with character spans stored in `spans_json` |
| LRC | Line highlight-start timestamps only; independent line clear times and character ends are lost |
| MI3 template ASS | Line display/clear intervals and whole-line highlight transition |

Use **JSON or CSV** for editable character templates. Enhanced LRC and supported ASS karaoke segments can also be imported. ASS positioning and styling are not reproduced in full; the player applies its own selected style.

**Export MI3 timing** writes JSON, CSV, LRC and ASS into a selected folder. It refuses to replace an existing template set. The JSON preserves original glyph codes and color controls for inspection; its default character spans retain an estimated-timing provenance label.

The simpler **Text / timestamps** window edits LRC text. Press F8 there to timestamp the current line; this is separate from character-end marking in the character editor.

## Export video

1. Enable **Enable export (off = preview only)**.
2. Choose an output format, resolution, frame rate, duration and audio source.
3. Click the export button and choose a new filename.

| Format | Output |
|---|---|
| MP4 / H.264 | Background video, still image or selected solid/key color with lyrics |
| MOV / ProRes 4444 | Lyrics only, with a truly transparent alpha background |

Transparent MOV uses ProRes 4444 (`ap4h`) with an alpha-capable pixel format. It preserves antialiased text edges and does not remove green pixels by chroma key. Background images, videos and solid colors are ignored for this output. The MOV can be composited in an alpha-capable video editor such as Adobe Premiere Pro; direct import into Premiere has not been tested on this workstation.

Supported presets are 640x360, 1280x720 and 1920x1080 at 24/25/30 fps. Duration must be greater than zero and no more than 24 hours. A MOV export can be much larger than an MP4.

Audio choices are **No audio**, **Input video audio** and **Current audio mix**. External MIDI synthesizer sound is not recorded into exported files. Select the current mix after loading and applying the audio settings.

Export runs in a background thread. Preview and export use independent decoders. Cancel removes the incomplete output. Existing videos are never overwritten.

## Supported formats and current limits

- Verified MI3 version-3 containers, MID03 resources and MDT3/4 music data.
- Supported SD3D/SN3 CA02/JA10 AAC audio at 44.1 kHz, stereo.
- Automatic playback of type-14 segmented audio events is not implemented. Use MIDI only or a manual mix where appropriate.
- SNG04 lyric lines and their display/highlight/clear times are verified against firmware. Character templates and substitute font geometry remain estimates.
- Original sound-generator ROMs, instrument patches, proprietary mixing and all custom glyph semantics are not reproduced.
- A valid MIDI output device is needed to hear MIDI. SD3 audio does not require one.

## Troubleshooting

**The launcher reports a missing runtime:** extract the entire ZIP and keep all folders together. Do not copy only the `.cmd` file.

**MIDI is silent:** choose an output device, enable destinations in the routing table and apply settings. Avoid selecting the same device for more than one port. Some external devices must be connected before refreshing the device list.

**The wrong audio plays:** verify that MI3 and SD3 belong to the same song, then check the selected resource and playback mode.

**Lyrics look wrong:** choose a font covering the lyric language. Unknown custom glyphs remain hexadecimal placeholders; filtering them hides the placeholder rather than decoding its meaning.

**Export contains no synthesizer sound:** exports include only the selected video audio or SD3 mix; external MIDI output is not captured.

**A feature reports an unsupported format:** do not assume similarly named files use the same format. Error messages identify the unsupported variant. Additional diagnostics are written to `player.log` beside the application.

Native Windows file dialogs and audio/MIDI device names can use the language of your operating system or drivers even though application-owned UI text is English.

## Offline checks and development

```powershell
.\runtime\python.exe .\check_dependencies.py
.\runtime\python.exe .\app.py --mi3 C:\Music\CE000001.MI3 --sd3 C:\Music\CE000001.SD3
```

The dependency check opens and closes a hidden player window and enumerates audio/MIDI devices; it does not play a song.

The portable runtime includes Python 3.12 x64, Tk, NumPy, PyAV/FFmpeg, Pillow, sounddevice/PortAudio, mido and their dependencies. `python312._pth` isolates it from user-installed Python packages. Keep the runtime's license and package metadata files. See `portable_manifest.json` for package versions and runtime hashes, and `localization_manifest.json` for English-edition details.

For development outside the portable runtime, use Python with Tk and install `requirements.txt`. `build_portable.py` builds an offline Windows Python 3.12 x64 package; `--repack` packages an existing runtime. Source conversion to this edition replaces application string constants; MIDI/audio algorithms and timing structures retain the 0.8 behavior.


## Version 0.8: firmware-derived timing corrections

Timing recognition now uses the original display_cs, sing_cs and clear_cs fields directly. Sweep rate is speed_raw*multiplier//100. Pixel increments use the difference of integer positions at absolute 100 Hz clocks, matching the verified MIPS arithmetic. Estimated character boundaries are inverted on the native centisecond clock instead of interpolating continuously between event endpoints.

A pause exactly between characters now delays the next character until motion resumes. Main/sub lanes remain independent, and simultaneous controls retain their file order. Arithmetic outside the verified 32-bit range produces an explicit error rather than silently generating timing.

Substitute font metrics still make character timestamps estimates. Provenance is estimated-speed-font-v2-cs, or estimated-speed-width-v2-cs without the font. Lines with no usable motion retain a labeled fallback. Existing imported JSON/CSV and manual timing edits are preserved. Linear within-character coloring and both line-advance modes remain available.

Both language editions share the identical lyric_clock.py module. Each edition passes 44 regression tests, including original MIPS arithmetic cases, pause boundaries and independent per-tick accumulation for all six real SNG resources. JSON template metadata describes the native 100 Hz clock and estimated character timing explicitly.


## Version 0.12: lyric visibility timing

Open **Visibility timing...** from the video/lyrics panel. Enable **Enable visibility timing**, adjust the sliders or millisecond fields, then click **Apply**. This feature is off by default to preserve previous behavior. **Restore illustrated defaults** enables it and sets: normal lead 4000ms, hold 2000ms, fade-in 200ms, fade-out 200ms, early filling on, maximum lead 6000ms. Click Apply after restoring defaults.

The normal lead is measured before the first sung character of each displayed row. The hold begins after its last character completes, followed by the fade-out. Fades use a smooth easing curve; character color sweeps remain linear. Values accept integers from 0 to 60000ms; zero fade means an immediate appearance/disappearance. With early filling enabled, maximum lead cannot be smaller than normal lead.

Early filling schedules fixed screen slots independently: once a row has finished its hold and fade-out, the next row can occupy that slot up to the maximum lead before singing. This overrides whole-screen replacement. With early filling off and per-line advance off, the next group waits until the current group finishes all holds/fades. Per-line advance also respects hold/fade duration while these settings are enabled and uses fixed-slot replacement. If no slot is available, display may occur later than the preferred lead. No song, audio/MIDI, lyric offsets or character timestamps are shifted.

Opacity affects lyrics and strokes only, never the video/image background. Transparent MOV retains straight alpha, including partially opaque edges. Preview, MP4 and MOV share the same deterministic schedule; seeking restores the appropriate state. Long-line wrapping and screen capacity remain active. Settings apply to the current session and are not yet persisted across launches.

Six new regression checks cover scheduling, limits, zero durations, fade opacity, seeking, MOV readback and dialog validation/cleanup. Each language edition has 50 regression tests.
