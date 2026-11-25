from __future__ import annotations

from pathlib import Path

from whisper_core import (
    DEFAULT_RECORDINGS_DIR,
    DEFAULTS,
    load_config,
    resolve_save_dir,
    saved_recording_path,
    transcribe_options,
)


def test_defaults_when_no_file() -> None:
    cfg = load_config(Path("/nonexistent/tabelhawhisper-test.toml"))
    assert cfg["model"] == DEFAULTS["model"]
    assert cfg["copy_clipboard"] is True
    assert cfg["history_size"] == 100
    assert "live_mode" not in cfg  # removed in v2.0
    assert "partial_interval" not in cfg
    assert "indicator" not in cfg


def test_override_merges(tmp_path: Path) -> None:
    p = tmp_path / "c.toml"
    p.write_text('model = "small"\nlanguage = "en"\nmode = "streaming"\n')
    cfg = load_config(p)
    assert cfg["model"] == "small"
    assert cfg["language"] == "en"
    assert cfg["history_size"] == 100  # default preserved


def test_transcribe_options_resolves_auto() -> None:
    cfg = {"language": "auto", "multilingual": True}
    lang, ml = transcribe_options(cfg)
    assert lang is None
    assert ml is True


def test_transcribe_options_resolves_pinned() -> None:
    cfg = {"language": "pt", "multilingual": False}
    lang, ml = transcribe_options(cfg)
    assert lang == "pt"
    assert ml is False


def test_transcribe_options_resolves_empty_as_auto() -> None:
    cfg = {"language": "", "multilingual": True}
    lang, ml = transcribe_options(cfg)
    assert lang is None
    assert ml is True


def test_new_defaults() -> None:
    cfg = load_config(Path("/nonexistent/tabelhawhisper-test.toml"))
    assert cfg["mode"] == "wav"
    assert cfg["save_audio"] is False
    assert cfg["save_audio_dir"] == ""
    assert cfg["send_to_agent"] is False


def test_mode_override_is_kept(tmp_path: Path) -> None:
    p = tmp_path / "c.toml"
    p.write_text('mode = "streaming"\n')
    assert load_config(p)["mode"] == "streaming"


def test_save_disabled_ignores_dir() -> None:
    assert resolve_save_dir({"save_audio": False, "save_audio_dir": "/srv/rec"}) is None


def test_save_string_false_is_disabled() -> None:
    assert resolve_save_dir({"save_audio": "false", "save_audio_dir": "/srv/rec"}) is None


def test_save_empty_dir_uses_default() -> None:
    assert resolve_save_dir({"save_audio": True, "save_audio_dir": ""}) == DEFAULT_RECORDINGS_DIR


def test_save_dir_expands_tilde() -> None:
    got = resolve_save_dir({"save_audio": True, "save_audio_dir": "~/rec"})
    assert got == Path.home() / "rec"


def test_save_relative_dir_is_under_home() -> None:
    got = resolve_save_dir({"save_audio": True, "save_audio_dir": "Music/takes"})
    assert got == Path.home() / "Music" / "takes"


def test_save_absolute_dir() -> None:
    assert resolve_save_dir({"save_audio": True, "save_audio_dir": "/srv/rec"}) == Path("/srv/rec")


def test_saved_recording_path_dedups(tmp_path: Path) -> None:
    ts = 1_700_000_000.0
    first = saved_recording_path(tmp_path, ts)
    assert first.suffix == ".wav"
    first.write_bytes(b"")
    second = saved_recording_path(tmp_path, ts)
    assert second.name == f"{first.stem}-1.wav"
    second.write_bytes(b"")
    assert saved_recording_path(tmp_path, ts).name == f"{first.stem}-2.wav"
