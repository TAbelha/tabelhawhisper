from __future__ import annotations

import json
from pathlib import Path

from whisper_core import (
    DEFAULTS,
    HISTORY_PATH,
    LEVELS_PATH,
    STATE_PATH,
    load_config,
    read_history,
    read_state,
    transcribe_options,
    write_history,
    write_levels,
    write_state,
)


def test_defaults_when_no_file() -> None:
    cfg = load_config(Path("/nonexistent/test.toml"))
    assert cfg["model"] == DEFAULTS["model"]
    assert "live_mode" not in cfg  # removed in v2.0
    assert cfg["history_size"] == 100


def test_atomic_write_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("whisper_core.STATE_PATH", tmp_path / "state.json")
    write_state({"state": "recording", "start": 123})
    result = read_state()
    assert result["state"] == "recording"
    assert result["start"] == 123


def test_write_state_preserves_existing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("whisper_core.STATE_PATH", tmp_path / "state.json")
    write_state({"state": "recording", "start": 100, "text": ""})
    write_state({"text": "hello"})
    result = read_state()
    assert result["state"] == "recording"
    assert result["start"] == 100
    assert result["text"] == "hello"


def test_read_state_invalid_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("whisper_core.STATE_PATH", tmp_path / "state.json")
    (tmp_path / "state.json").write_text("not json {{{")
    result = read_state()
    assert result == {"state": "idle"}


def test_write_levels(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("whisper_core.LEVELS_PATH", tmp_path / "levels.json")
    write_levels([0.1, 0.5, 0.3])
    result = json.loads((tmp_path / "levels.json").read_text())
    assert result["levels"] == [0.1, 0.5, 0.3]


def test_read_history_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("whisper_core.HISTORY_PATH", tmp_path / "history.json")
    result = read_history()
    assert result == {"entries": []}


def test_write_history_ring(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("whisper_core.HISTORY_PATH", tmp_path / "history.json")
    for i in range(5):
        write_history({"ts": i, "text": f"t{i}"}, history_size=3)
    h = read_history()
    assert len(h["entries"]) == 3
    assert h["entries"][0]["ts"] == 2  # oldest kept
    assert h["entries"][2]["ts"] == 4  # newest
