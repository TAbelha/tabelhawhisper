"""--send resolution and delivery from the queue worker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tabelhawhisper as tw
import whisper_core
import whisper_queue
from tabelhawhisper import resolve_send

TARGET = {"session": "twtest", "pane_id": "p1", "agent": "claude", "label": "claude"}


@pytest.mark.parametrize(
    ("cli", "at_start", "cfg", "expected"),
    [
        (None, None, False, False),
        (None, None, True, True),
        (None, None, "yes", False),
        (None, True, False, True),
        (False, True, True, False),
        (True, False, False, True),
    ],
)
def test_resolve_send_precedence(cli, at_start, cfg, expected) -> None:
    assert resolve_send(cli, at_start, cfg) is expected


@pytest.fixture
def worker_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qpaths: Path) -> dict:
    monkeypatch.setattr(whisper_core, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(tw, "LOG_FILE", tmp_path / "tw.log")
    out: dict = {"notes": [], "clip": [], "delivered": []}
    monkeypatch.setattr(tw, "_notify", lambda t: out["notes"].append(t))
    monkeypatch.setattr(tw, "_clipboard_store", lambda t: out["clip"].append(t))
    monkeypatch.setattr(tw, "transcribe_file", lambda *_a: "olá\nmundo")
    wav = tmp_path / "tabelhawhisper-1.wav"
    wav.write_bytes(b"")
    out["job"] = {
        "id": "1",
        "wav": str(wav),
        "mode": "wav",
        "attempts": 1,
        "saved": None,
        "send": True,
        "target": TARGET,
        "target_error": None,
        "delivered": False,
    }
    whisper_queue.enqueue(out["job"])
    return out


def _hist() -> list:
    return json.loads(whisper_core.HISTORY_PATH.read_text())["entries"]


def test_process_job_delivers(worker_env: dict, monkeypatch) -> None:
    monkeypatch.setattr(
        tw, "deliver", lambda target, text: worker_env["delivered"].append((target, text))
    )
    tw._process_job(worker_env["job"], {"model": "x", "language": "pt"})
    assert worker_env["delivered"] == [(TARGET, "olá\nmundo")]
    assert _hist()[-1]["sent_to"] == "claude"
    assert worker_env["notes"][-1].startswith("Enviado para claude")
    assert worker_env["clip"] == []
    saved = whisper_queue.read_job(whisper_queue.list_jobs()[0])
    assert saved is not None and saved["delivered"] is True


def test_process_job_does_not_resend(worker_env: dict, monkeypatch) -> None:
    worker_env["job"]["delivered"] = True
    monkeypatch.setattr(tw, "deliver", lambda *_a: pytest.fail("sent twice"))
    tw._process_job(worker_env["job"], {"model": "x", "language": "pt"})
    assert _hist()[-1]["sent_to"] == "claude"


def test_process_job_delivery_failure_falls_back(worker_env: dict, monkeypatch) -> None:
    monkeypatch.setattr(tw, "deliver", lambda *_a: "agente aguardando aprovação")
    tw._process_job(worker_env["job"], {"model": "x", "language": "pt"})
    assert _hist()[-1]["send_error"] == "agente aguardando aprovação"
    assert worker_env["clip"] == ["olá\nmundo"]
    assert worker_env["notes"][-1].startswith("não enviado: agente aguardando aprovação")


def test_process_job_target_error_falls_back(worker_env: dict, monkeypatch) -> None:
    worker_env["job"].update(target=None, target_error="painel focado não é agente")
    monkeypatch.setattr(tw, "deliver", lambda *_a: pytest.fail("no target"))
    tw._process_job(worker_env["job"], {"model": "x", "language": "pt"})
    assert _hist()[-1]["send_error"] == "painel focado não é agente"
    assert worker_env["clip"] == ["olá\nmundo"]


def test_process_job_without_send_is_plain(worker_env: dict, monkeypatch) -> None:
    worker_env["job"].update(send=False, target=None, target_error=None)
    monkeypatch.setattr(tw, "deliver", lambda *_a: pytest.fail("not requested"))
    tw._process_job(worker_env["job"], {"model": "x", "language": "pt"})
    assert "sent_to" not in _hist()[-1] and "send_error" not in _hist()[-1]
    assert worker_env["notes"] == ["olá\nmundo"]


def test_stop_captures_target_when_send(tmp_path: Path, monkeypatch, qpaths: Path) -> None:
    monkeypatch.setattr(whisper_core, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(tw, "LEVELS_PATH", tmp_path / "levels.json")
    monkeypatch.setattr(tw, "PID_FILE", tmp_path / "pids.json")
    monkeypatch.setattr(tw, "LOG_FILE", tmp_path / "tw.log")
    monkeypatch.setattr(tw, "find_pwrec", list)
    monkeypatch.setattr(tw, "_kill", lambda _p: None)
    monkeypatch.setattr(tw, "_kick_worker", lambda: None)
    monkeypatch.setattr(tw, "capture_target", lambda: (TARGET, None))
    wav = tmp_path / "tabelhawhisper-5.wav"
    wav.write_bytes(b"")
    whisper_core.write_state(
        {"state": "recording", "mode": "wav", "wav": str(wav), "start": 1.0, "send": True}
    )
    tw.stop({})
    job = whisper_queue.read_job(whisper_queue.list_jobs()[0])
    assert job is not None and job["send"] is True and job["target"] == TARGET
