# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-09-12

### Added
- Floating recording pill (layer-shell overlay) with Stop and Cancel buttons,
  visible only while active. Cancel kills in-flight transcription instantly.
- Transcription is now cancellable via `whisper_dictate.py cancel`.
- `Mod+E` during transcription cancels the current one and starts a new
  recording immediately (no more waiting for the old transcription to finish).
- Per-session WAV files (`/tmp/whisper-dictate-<ts>.wav`) prevent a new
  recording from clobbering an in-flight transcription.
- State file now carries `python`, `script`, `wav`, and `indicator` fields
  so the pill can invoke commands without hardcoded paths.
- Config migration: `install.sh` automatically copies config from the old
  `~/.config/tabela/` dir to the new `~/.config/tabelha/` dir.

### Changed
- Default transcription model bumped from `small` to `medium` (still
  fully configurable via `config.toml`).
- Repository renamed from `tabelawhisper` to `tabelhawhisper` (GitHub redirect
  is automatic).
- Config dir corrected from `~/.config/tabela/` to `~/.config/tabelha/`.

## [1.0.1] - 2026-09-01

### Changed
- Repository renamed from `tabela-whisper` to `tabelawhisper` to match TabelaDev
  org naming convention. GitHub redirect is automatic.

## [1.0.0] - 2026-08-27

### Added
- Voice dictation toggle (niri keybind `Mod+E`) that records via `pw-record` and
  transcribes locally with faster-whisper, copying the result to the clipboard.
- DankMaterialShell bar widget `TAbelha Whisper` that appears only while
  recording/transcribing (elapsed timer + `Transcrevendo…`), and collapses out
  of the bar when idle so it never reserves space.
- Silent, lowest-tier desktop notification (app `TAbelha Whisper`) with the
  transcript on completion.
- `config.toml` support (`~/.config/tabelha/whisper-dictate/config.toml`) with
  model, language, device, beam size, multilingual, and live modes
  (`off` / `partial` / `streaming`).
- Orchestrator renames itself to `twhisper` (via `prctl`) for easy process
  identification; stuck recordings can be killed with `pkill -x pw-record`.
