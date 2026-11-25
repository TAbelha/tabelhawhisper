"""Orchestrator flow: stop -> queue -> worker, scoped cancels, toggle."""

from __future__ import annotations

import json
import signal
import wave
from pathlib import Path

import pytest

import tabelhawhisper as tw
import whisper_core
import whisper_queue
from whisper_core import read_state, write_state


def _make_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 1600)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qpaths: Path) -> dict:
    monkeypatch.setattr(whisper_core, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(whisper_core, "HISTORY_PATH", tmp_path / "hist" / "history.json")
    monkeypatch.setattr(tw, "LEVELS_PATH", tmp_path / "levels.json")
    monkeypatch.setattr(tw, "PID_FILE", tmp_path / "pids.json")
    monkeypatch.setattr(tw, "LOG_FILE", tmp_path / "tw.log")
    monkeypatch.setattr(tw, "find_pwrec", list)
    monkeypatch.setattr(tw, "_notify", lambda _text: None)
    monkeypatch.setattr(tw, "_clipboard_store", lambda _text: None)
    calls: dict = {"kill": [], "kicked": 0, "spawned": []}
    monkeypatch.setattr(tw, "_kill", lambda pids: calls["kill"].append(("soft", list(pids))))
    monkeypatch.setattr(tw, "_kill_force", lambda pids: calls["kill"].append(("force", list(pids))))

    def kick() -> None:
        calls["kicked"] += 1

    monkeypatch.setattr(tw, "_kick_worker", kick)
    calls["tmp"] = tmp_path
    return calls


def _recording(tmp_path: Path, *, state: str = "recording", ts: str = "1700000000000") -> str:
    wav = str(tmp_path / f"tabelhawhisper-{ts}.wav")
    _make_wav(Path(wav))
    write_state({"state": state, "mode": "wav", "wav": wav, "start": 1_700_000_000.0, "send": None})
    (tmp_path / "pids.json").write_text(json.dumps({"pids": [4242], "mode": "wav"}))
    return wav


def test_stop_enqueues_and_frees_recorder(env: dict) -> None:
    wav = _recording(env["tmp"])
    tw.stop({"save_audio": False})
    assert read_state()["state"] == "idle"
    jobs = whisper_queue.list_jobs()
    assert [p.stem for p in jobs] == ["1700000000000"]
    job = whisper_queue.read_job(jobs[0])
    assert job is not None
    assert job["wav"] == wav and job["saved"] is None and job["send"] is False
    assert whisper_queue.read_status() == 1
    assert env["kicked"] == 1
    assert env["kill"] == [("soft", [4242])]
    assert not (env["tmp"] / "pids.json").exists()


def test_stop_from_paused_works(env: dict) -> None:
    _recording(env["tmp"], state="paused")
    tw.stop({})
    assert read_state()["state"] == "idle"
    assert len(whisper_queue.list_jobs()) == 1


def test_stop_saves_copy_when_enabled(env: dict) -> None:
    _recording(env["tmp"])
    rec_dir = env["tmp"] / "recs"
    tw.stop({"save_audio": True, "save_audio_dir": str(rec_dir)})
    job = whisper_queue.read_job(whisper_queue.list_jobs()[0])
    assert job is not None and job["saved"]
    assert Path(job["saved"]).parent == rec_dir
    assert Path(job["saved"]).exists()


def test_save_off_ignores_dir(env: dict) -> None:
    _recording(env["tmp"])
    rec_dir = env["tmp"] / "recs"
    tw.stop({"save_audio": False, "save_audio_dir": str(rec_dir)})
    assert not rec_dir.exists()


def test_save_failure_still_queues(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    _recording(env["tmp"])

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(tw.shutil, "copy2", boom)
    tw.stop({"save_audio": True, "save_audio_dir": str(env["tmp"] / "recs")})
    job = whisper_queue.read_job(whisper_queue.list_jobs()[0])
    assert job is not None and job["saved"] is None
    assert read_state()["state"] == "idle"


def test_stop_does_not_clobber_newer_recording(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    _recording(env["tmp"])
    real_finalize = tw._finalize_wav

    def finalize_then_new_take(wav: str, timeout_s: float = 3.0) -> bool:
        ok = real_finalize(wav, timeout_s)
        write_state({"state": "recording", "wav": "/tmp/newer.wav"})
        return ok

    monkeypatch.setattr(tw, "_finalize_wav", finalize_then_new_take)
    tw.stop({})
    st = read_state()
    assert st["state"] == "recording" and st["wav"] == "/tmp/newer.wav"


def test_stop_lost_wav_reports_error(env: dict) -> None:
    wav = _recording(env["tmp"])
    Path(wav).unlink()
    tw.FINALIZE_TIMEOUT_S = 0.1
    try:
        tw.stop({})
    finally:
        tw.FINALIZE_TIMEOUT_S = 3.0
    assert read_state()["state"] == "error"
    assert whisper_queue.list_jobs() == []


def test_stop_when_idle_is_noop(env: dict) -> None:
    write_state({"state": "idle"})
    tw.stop({})
    assert read_state()["state"] == "idle"
    assert whisper_queue.list_jobs() == []


def test_toggle_never_cancels_while_transcribing(env: dict, monkeypatch) -> None:
    write_state({"state": "transcribing"})
    started: list = []
    monkeypatch.setattr(tw, "is_recording", lambda: False)
    monkeypatch.setattr(tw, "start", lambda cfg, send=None: started.append(send))
    tw.toggle({}, send=True)
    assert started == [True]
    assert env["kill"] == []


def test_toggle_stops_when_recording(env: dict, monkeypatch) -> None:
    write_state({"state": "recording"})
    stopped: list = []
    monkeypatch.setattr(tw, "is_recording", lambda: True)
    monkeypatch.setattr(tw, "stop", lambda cfg, send=None: stopped.append(send))
    tw.toggle({}, send=None)
    assert stopped == [None]


def test_kill_sends_sigcont_first(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list = []

    def fake_kill(pid: int, sig: int) -> None:
        sent.append(sig)
        if sig == signal.SIGINT:
            raise ProcessLookupError

    monkeypatch.setattr(tw.os, "kill", fake_kill)
    monkeypatch.setattr(tw.time, "sleep", lambda _s: None)
    tw._kill([1234])
    assert sent[0] == signal.SIGCONT


def test_worker_drains_queue_in_order(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp = env["tmp"]
    for ts in ("1000", "3000", "2000"):
        _make_wav(tmp / f"tabelhawhisper-{ts}.wav")
        whisper_queue.enqueue(
            {
                "id": ts,
                "wav": str(tmp / f"tabelhawhisper-{ts}.wav"),
                "mode": "wav",
                "attempts": 0,
                "saved": None,
            }
        )
    seen: list = []
    monkeypatch.setattr(tw, "transcribe_file", lambda wav, *a: seen.append(wav) or f"t{wav[-8:-4]}")
    monkeypatch.setattr(tw, "load_config", lambda: {"model": "x", "language": "pt"})
    monkeypatch.setattr(tw, "_set_procname", lambda _n: None)
    tw.work()
    assert [Path(w).stem.rsplit("-", 1)[1] for w in seen] == ["1000", "2000", "3000"]
    assert whisper_queue.list_jobs() == []
    assert whisper_queue.read_status() == 0
    hist = json.loads(whisper_core.HISTORY_PATH.read_text())["entries"]
    assert len(hist) == 3


def test_worker_transcribe_error_goes_to_history(env: dict, monkeypatch) -> None:
    tmp = env["tmp"]
    _make_wav(tmp / "tabelhawhisper-1000.wav")
    whisper_queue.enqueue(
        {"id": "1000", "wav": str(tmp / "tabelhawhisper-1000.wav"), "mode": "wav", "attempts": 0}
    )

    def boom(*_a):
        raise RuntimeError("model missing")

    monkeypatch.setattr(tw, "transcribe_file", boom)
    monkeypatch.setattr(tw, "load_config", lambda: {"model": "x", "language": "pt"})
    monkeypatch.setattr(tw, "_set_procname", lambda _n: None)
    tw.work()
    hist = json.loads(whisper_core.HISTORY_PATH.read_text())["entries"]
    assert hist[-1]["state"] == "error"
    assert whisper_queue.list_jobs() == []


def test_cancel_recording_keeps_queue(env: dict) -> None:
    tmp = env["tmp"]
    _make_wav(tmp / "tabelhawhisper-1.wav")
    whisper_queue.enqueue({"id": "1", "wav": str(tmp / "tabelhawhisper-1.wav")})
    wav = _recording(tmp, ts="2")
    tw.cancel_recording({})
    assert read_state()["state"] == "idle"
    assert not Path(wav).exists()
    assert [p.stem for p in whisper_queue.list_jobs()] == ["1"]
    assert env["kill"] == [("force", [4242])]


def test_cancel_queue_keeps_recording(env: dict, monkeypatch) -> None:
    tmp = env["tmp"]
    _make_wav(tmp / "tabelhawhisper-1.wav")
    whisper_queue.enqueue({"id": "1", "wav": str(tmp / "tabelhawhisper-1.wav")})
    _recording(tmp, ts="2")
    monkeypatch.setattr(tw, "worker_pid", lambda: 777)
    monkeypatch.setattr(tw, "_is_worker", lambda pid: pid == 777)
    tw.cancel_queue({})
    assert whisper_queue.list_jobs() == []
    assert not (tmp / "tabelhawhisper-1.wav").exists()
    assert read_state()["state"] == "recording"
    assert env["kill"] == [("force", [777])]


def test_cancel_queue_skips_unrelated_pid(env: dict, monkeypatch) -> None:
    monkeypatch.setattr(tw, "worker_pid", lambda: 778)
    monkeypatch.setattr(tw, "_is_worker", lambda _pid: False)
    tw.cancel_queue({})
    assert env["kill"] == []


def test_cancel_alias_dispatches(env: dict, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(tw, "cancel_recording", lambda cfg: calls.append("rec"))
    monkeypatch.setattr(tw, "cancel_queue", lambda cfg: calls.append("queue"))
    write_state({"state": "recording"})
    tw.cancel({})
    write_state({"state": "idle"})
    tw.cancel({})
    assert calls == ["rec", "queue"]
