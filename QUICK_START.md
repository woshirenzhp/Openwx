# Quick start — Openjs-wx 0.15 English

1. Extract the entire ZIP and run `MI3_SD3_Player_EN/start_player.cmd`.
2. Choose MI3/MIDI, audio (SD3/WAV/AAC/MP3/FLAC/APE/ALAC), or both, then click **Load files**.
3. Select a music resource and playback mode. Choose audio/MIDI outputs and assign MIDI tracks to A/B/C/D.
4. Click **Apply settings (restart)**, then **Play**.
5. Open **Video / Lyrics / Export...** for backgrounds, lyric previews, timing edits and video export.

## Lyrics

- MI3 character templates load automatically. They are estimates and can be corrected in **Character timeline...**.
- Each character fills from left to right between its start and end times.
- **Advance after each line** off: replace the whole screen after every visible row finishes.
- **Advance after each line** on: roll forward when the top row finishes.
- **Filter [4-digit codes]** optionally hides markers such as `[0125]` without changing the original text.
- Save **JSON or CSV** to keep complete character timing. LRC does not preserve it.

## Video export

Enable export explicitly. Select MP4 for a background/green-screen video, or **MOV / ProRes 4444** for lyrics with a transparent alpha background. Choose a new output filename.

External MIDI synthesizer sound is not captured. Export audio can use the input video's audio or the current audio mix.

See [README.md](README.md) for keyboard shortcuts, format support and troubleshooting.

Open **Visibility timing...**, enable it and apply to adjust lead, hold, fades and early slot filling.

## Subtitle files

MIDI/XF embedded lyrics load automatically. Import or export XF/SRT/VTT/ASS/SSA/TTML/DFXP/SCC with the lyric buttons or the character timeline. See SUBTITLE_FORMATS.md for timing and character-set limits.

## Edit during preview

Click Edit lyrics... F2 or press F2 in a video/green-screen preview. Valid line edits auto-commit after 350 ms and update previews. Add/delete lines, adjust character times or use 1 ms nudges. Save JSON/CSV to keep the editable result; live application does not save to disk. F10 toggles preview controls.

## Projects

Use Project > Save reference project as... for a small .opw containing lyrics/settings and resource paths. Save packed project as... creates a .opx with linked media and fonts. Open either edition's project with Ctrl+O. Opening stays paused. See PROJECTS.md for missing-file relocation and persistent packed-resource caches.
