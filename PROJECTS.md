# Projects · Openjs-wx 0.15

Version 0.15 uses `.opw` for reference projects and `.opx` for packed projects. Legacy `.mi3proj` / `.mi3pack` files can still be opened; Ctrl+S saves them under the corresponding new extension. The internal project format is unchanged.

Use the main window's **Project** menu. Ctrl+O opens a project. Ctrl+S saves the current project, defaulting to a reference project for the first save. Ctrl+Shift+S saves a packed copy. Command line: `runtime\python.exe app.py --project "D:\song.opx"`.

| Type | File | Contents and use |
|---|---|---|
| Reference project | `.opw` | UTF-8 JSON with complete lyrics/settings and paths to media/fonts; small and suitable for local editing. |
| Packed project | `.opx` | ZIP containing manifest.json and all linked resources; suitable for moving between computers without copying original media separately. |

## Saved state

- Raw lyrics, independent display/sing/clear times, character/syllable spans and provenance. The filter flag is stored separately; raw markers remain editable.
- MI3 or every loaded SMF, SD3 or external audio, video/image background and the current font file. The same physical file is stored once; equal filenames in different directories remain separate.
- Selected music resource, playback mode, audio/MIDI offsets, master and audio-track gains, A/B/C/D source settings and per-track routing for each configured music resource.
- Font size/colors/stroke, page/line switching, lead/hold/fade settings, lyric/video offsets, output size/frame rate/format/audio/duration and preview/export toggles.
- Separate main-player and independent-preview positions. Opening stays paused. Saved preview types may reopen, but playback and video export do not start automatically.

Saving commits a valid current line draft and applies it to the preview. With several editors, the most recently opened editor belonging to the current lyric revision is used; stale drafts cannot replace a new song. Correct invalid fields first. Load newly selected media before saving so old-session lyrics are not paired with unloaded new paths. Lyrics/background-only projects are also supported.

## Reference projects

Paths are stored relative to the project where possible, with the original absolute path as a fallback. Retain the relative folder structure when moving a project and its resources. Same-named files beside the project are also tried. Missing files can be relocated; other files in the newly chosen directory are searched by name. Cancelling relocation keeps the current session.

A reference project reads the current source files rather than freezing their contents. Size changes are reported; incompatible MIDI-track or music-resource structure causes an error. Use a packed project for a fixed resource snapshot.

## Packed projects and cache

Resources are copied in chunks with SHA-256 checksums, without media transcoding. Saving writes a temporary file and replaces the destination only after successful completion. Wait for **Project saved** before exiting.

Opening validates and extracts files into `project_cache` beside the player. An unchanged project reuses its verified cache. A damaged cache is extracted again while preserving the old copy, since another reference project might still link to it. The first open needs enough free space for all extracted resources. Caches persist after closing.

A reference project saved from an opened packed project may point into that cache. Retain it, or copy/relink its resources. Only clean old caches after checking that no reference project uses them and retaining the corresponding packed project.

Example:

```
song.opx
├─ manifest.json
└─ assets/
   ├─ r0/song.mid
   ├─ r1/second.mid
   ├─ r2/backing.flac
   ├─ r3/background.mp4
   └─ r4/font.ttf
```

## Languages and devices

The language-neutral format works in both Chinese and English editions. Lyrics and filenames retain their language. External MIDI synthesizers, drivers and hardware sounds are not packaged. Device names and routing are saved and matched on the other computer. Missing MIDI outputs are disabled; missing audio devices use the system default, with a diagnostic message. Review output choices before playing.

Projects contain data, not executable scripts. Unsupported versions, malformed archive paths, corrupt resources and checksum failures are rejected. A project is not a rendered video or a recording of an external MIDI synth; use video export to produce the final media.
