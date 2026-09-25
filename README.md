# tabelhawhisper

Voice dictation plugin for [DankMaterialShell](https://github.com/niceDev0908/DankMaterialShell):
record audio, transcribe locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
copy to clipboard, with a floating pill overlay and a transcription history widget.

## Features

- **Two recording modes:** wav (file-based, with pause) and streaming (pipe-based, no pause)
- **Floating pill:** shows recording/paused/transcribing status with real-time wave bars
- **Pause/Resume:** SIGSTOP/SIGCONT in wav mode, hidden in streaming mode
- **Wave bars:** real PCM levels from mic, rendered as animated bars in the pill
- **History widget:** persistent ring buffer in the bar, expand entries, copy to clipboard
- **Clipboard integration:** auto-copy on completion + DMS clipboard service + wl-copy
- **Notifications:** silent desktop notification on completion
- **Local transcription:** no cloud, no API keys, everything runs on your machine

## Requirements

- Python 3.12+
- PipeWire (`pw-record`)
- faster-whisper (installed automatically via uv)
- DankMaterialShell (for the floating pill and history widget)
- `notify-send` and `wl-clipboard` (`wl-copy`)

## Install

```bash
git clone https://github.com/TAbelha/tabelhawhisper.git
cd tabelhawhisper
./install.sh
```

The installer:
1. Syncs the uv environment (installs faster-whisper, numpy, etc.)
2. Sets up the niri keybind wrapper (`Mod+E`)
3. Symlinks the DMS plugin
4. Creates the config file

## Usage

- **Mod+E** to start/stop recording (wav mode default)
- **Pill appears** during recording with wave bars, timer, and controls
- **Pause button** (wav mode only) pauses/resumes recording
- **Stop button** finishes recording and starts transcription
- **Cancel button** discards the recording
- **History widget** in the DMS bar shows past transcriptions (click to expand, copy)

## Config

Edit `~/.config/tabelha/tabelhawhisper/config.toml`:

```toml
model = "small"           # base | small | medium | large-v3
language = "auto"          # auto detects pt/en mixed; or pin "pt"/"en"
multilingual = true        # code-switching support
mode = "wav"               # wav (pausa) | streaming (no pausa)
copy_clipboard = true      # auto-copy transcript on completion
history_size = 100         # max history entries (ring buffer)
beam_size = 5              # higher = more accurate, slower
engine = "faster-whisper"  # transcription engine
device = "cpu"             # cpu or cuda
```

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Mod+E | Toggle recording |
| Mod+Shift+E | Cancel recording |

## Plugin Structure

The plugin is a **composite** DMS plugin with two components:

- **DictatePill.qml** (daemon): floating overlay with recording controls, wave bars, and transcription status
- **HistoryWidget.qml** (bar widget): history icon in the bar, popout with expandable entries and copy

## License

AGPL-3.0
