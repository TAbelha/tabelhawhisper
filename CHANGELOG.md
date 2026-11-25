# Changelog

## Unreleased

## 3.0.0

- **Breaking:** internal ids renamed from `whisper-dictate`/`whisperDictate` to `tabelhawhisper`: DMS plugin id and IPC target (`dms ipc call tabelhawhisper ...`), plugin dir, `bin/tabelhawhisper.py`, config dir (`~/.config/tabelha/tabelhawhisper/`), niri wrapper (`tabelhawhisper.sh`), `/tmp/tabelhawhisper*` runtime files, `TABELHAWHISPER_CONFIG` env var
- `install.sh` migrates the old config dir (keeping `history.json`) and removes the old plugin symlink and niri wrapper
- After upgrading: re-run `install.sh`, re-enable the TAbelhaWhisper plugin in DMS, and point the Mod+E bind at `tabelhawhisper.sh`
- Transcription queue (wav mode): stopping hands the take to a background worker and frees the recorder, so a new take can start while earlier ones transcribe; the pill shows a pending badge and "Transcrevendo... (N)"
- **Behavior change:** Mod+E during transcription now starts a new take instead of cancelling; the pill's ✕ cancels only the recording (`cancel-recording`) or only the queue (`cancel-queue`)
- Wave bars use a noise gate that learns the background floor, so steady music/fan noise no longer moves them (display only)
- Spinner rotates in place (fixed-size arc instead of a glyph)
- Pause no longer counts towards the pill timer
- `save_audio` / `save_audio_dir`: optional copy of each take (default dir `~/.local/share/tabelha/tabelhawhisper/recordings`)
- `send_to_agent` and `--send/--no-send`: submit the transcript to the herdr agent pane focused at stop time; falls back to the clipboard with the reason when it cannot
- Fix: `mode` from the config file was ignored (missing from the defaults)
- Stopping while paused works (processes get SIGCONT before being stopped)
- Dependencies: security updates flagged by pip-audit (urllib3, msgpack, setuptools, filelock, certifi; av 18.1.0 was yanked, now 18.1.1)

## 2.0.0

- Floating pill overlay with recording controls, wave bars, and transcription status
- Pause/resume support in wav mode (SIGSTOP/SIGCONT)
- Two recording modes: wav (file-based) and streaming (pipe-based)
- Real-time PCM levels rendered as wave bars in the pill
- Transcription history widget in the DMS bar
- Persistent history ring buffer (~/.config/tabelha/whisper-dictate/history.json)
- History entries expandable with copy to clipboard via DMS clipboard service
- Composite plugin type (daemon pill + widget bar)
- DMS clipboard service integration (clipboard.store)
- Atomic state/levels/history writes (tmp+rename pattern)
- Thread-safe levels file (separate from state file)
- Config: removed live_mode/partial_interval/indicator, added history_size/mode
- Removed partial mode (redundant with streaming)
- Repo moved to TAbelha org

## 1.1.0

- Initial release with DMS bar widget
- Streaming transcription mode
- Clipboard auto-copy
- Silent desktop notification

## 1.0.1

- Rename from tabela-whisper to tabelhawhisper
- Config dir migration: ~/.config/tabela/ -> ~/.config/tabelha/

## 1.0.0

- Initial release
