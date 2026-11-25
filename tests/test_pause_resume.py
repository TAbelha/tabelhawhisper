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


def test_resume_excludes_paused_time(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("whisper_core.STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr("tabelhawhisper.PID_FILE", tmp_path / "pids.json")
    (tmp_path / "pids.json").write_text(json.dumps({"pids": [99999], "mode": "wav"}))
    write_state({"state": "recording", "mode": "wav", "start": 1000.0})
    from tabelhawhisper import pause, resume
    from whisper_core import read_state

    with patch("tabelhawhisper.os.kill"), patch("tabelhawhisper.time.time", return_value=1020.0):
        pause({})
    with patch("tabelhawhisper.os.kill"), patch("tabelhawhisper.time.time", return_value=1030.0):
        resume({})
    state = read_state()
    assert state["start"] == 1010.0  # 10 s paused no longer counts: elapsed is back to 20
    assert state["paused_at"] is None
