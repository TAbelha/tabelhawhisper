# Changelog

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
