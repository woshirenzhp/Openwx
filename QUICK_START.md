# Quick start — Openjs-wx 0.7 English

1. Extract the entire ZIP and run `MI3_SD3_Player_EN/start_player.cmd`.
2. Choose an MI3 and the matching SD3, then click **Load files**.
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

External MIDI synthesizer sound is not captured. Export audio can use the input video's audio or the current SD3 mix.

See [README.md](README.md) for keyboard shortcuts, format support and troubleshooting.
