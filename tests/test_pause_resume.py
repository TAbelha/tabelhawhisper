from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from whisper_core import write_state


def test_pause_from_idle_is_noop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("whisper_core.STATE_PATH", tmp_path / "state.json")
    write_state({"state": "idle"})
    from tabelhawhisper import pause
    pause({})
    from whisper_core import read_state
    assert read_state()["state"] == "idle"


def test_pause_from_recording(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("whisper_core.STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr("tabelhawhisper.PID_FILE", tmp_path / "pids.json")
    write_state({"state": "recording", "mode": "wav"})
    (tmp_path / "pids.json").write_text(json.dumps({"pids": [99999], "mode": "wav"}))
    from tabelhawhisper import pause
    with patch("tabelhawhisper.os.kill"):
        pause({})
    from whisper_core import read_state
    assert read_state()["state"] == "paused"


def test_resume_from_idle_is_noop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("whisper_core.STATE_PATH", tmp_path / "state.json")
    write_state({"state": "idle"})
    from tabelhawhisper import resume
    resume({})
    from whisper_core import read_state
    assert read_state()["state"] == "idle"


def test_resume_from_paused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("whisper_core.STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr("tabelhawhisper.PID_FILE", tmp_path / "pids.json")
    write_state({"state": "paused", "mode": "wav"})
    (tmp_path / "pids.json").write_text(json.dumps({"pids": [99999], "mode": "wav"}))
    from tabelhawhisper import resume
    with patch("tabelhawhisper.os.kill"):
        resume({})
    from whisper_core import read_state
    assert read_state()["state"] == "recording"
