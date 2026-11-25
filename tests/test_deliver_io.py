from __future__ import annotations

import json
import subprocess

import pytest

import whisper_deliver as wd

TARGET = {"session": "work", "pane_id": "w:p2", "agent": "claude", "label": "x"}


@pytest.fixture
def fake_herdr(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    monkeypatch.setattr(wd, "herdr_bin", lambda: "/bin/herdr")
    return []


def test_deliver_success_builds_argv(fake_herdr, monkeypatch) -> None:
    def run(argv, timeout):
        fake_herdr.append(argv)
        return 0, ""

    monkeypatch.setattr(wd, "_run", run)
    assert wd.deliver(TARGET, "oi\ntudo bem") is None
    assert fake_herdr == [
        ["/bin/herdr", "--session", "work", "agent", "prompt", "w:p2", "oi tudo bem"]
    ]


def test_deliver_reports_herdr_error(fake_herdr, monkeypatch) -> None:
    out = json.dumps({"error": {"code": "agent_blocked", "message": "blocked"}})
    monkeypatch.setattr(wd, "_run", lambda argv, timeout: (1, out))
    assert wd.deliver(TARGET, "oi") == "agente aguardando aprovação"


def test_deliver_timeout(fake_herdr, monkeypatch) -> None:
    def run(argv, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)

    monkeypatch.setattr(wd, "_run", run)
    assert wd.deliver(TARGET, "oi") == "herdr não respondeu a tempo"


def test_deliver_without_herdr(monkeypatch) -> None:
    monkeypatch.setattr(wd, "herdr_bin", lambda: None)
    assert wd.deliver(TARGET, "oi") == "herdr não encontrado"


def test_deliver_empty_text(fake_herdr) -> None:
    assert wd.deliver(TARGET, "  \n ") == "transcrição vazia"


def test_capture_target_end_to_end(monkeypatch) -> None:
    monkeypatch.setattr(wd.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(wd, "herdr_bin", lambda: "/bin/herdr")
    monkeypatch.setattr(
        wd,
        "_read_procs",
        lambda: {
            6899: (1, ["ghostty"]),
            14501: (6899, ["herdr", "session", "attach", "work"]),
        },
    )
    replies = {
        "focused-window": json.dumps({"id": 4, "pid": 6899}),
        "windows": json.dumps([{"id": 4, "pid": 6899}, {"id": 9, "pid": 1}]),
        "list": json.dumps(
            {"result": {"panes": [{"pane_id": "w:p2", "focused": True, "agent": "claude"}]}}
        ),
    }
    monkeypatch.setattr(wd, "_run", lambda argv, timeout: (0, replies[argv[-1]]))
    target, reason = wd.capture_target()
    assert reason is None
    assert target == {"session": "work", "pane_id": "w:p2", "agent": "claude", "label": "claude"}


def test_capture_target_never_raises(monkeypatch) -> None:
    monkeypatch.setattr(wd.shutil, "which", lambda name: f"/usr/bin/{name}")

    def boom(argv, timeout):
        raise RuntimeError("kaput")

    monkeypatch.setattr(wd, "_run", boom)
    target, reason = wd.capture_target()
    assert target is None
    assert reason is not None
    assert "kaput" in reason


def test_capture_target_browser_focused(monkeypatch) -> None:
    monkeypatch.setattr(wd.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(wd, "_read_procs", lambda: {8664: (1, ["brave"])})
    replies = {
        "focused-window": json.dumps({"id": 29, "pid": 8664}),
        "windows": json.dumps([{"id": 29, "pid": 8664}]),
    }
    monkeypatch.setattr(wd, "_run", lambda argv, timeout: (0, replies[argv[-1]]))
    assert wd.capture_target() == (None, "janela focada não tem herdr")
