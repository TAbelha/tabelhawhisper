from __future__ import annotations

import pytest

from whisper_deliver import (
    choose_session,
    descendants,
    herdr_client_sessions,
    normalize_text,
    parse_client_session,
    parse_herdr_output,
    parse_stat_ppid,
    reason_for,
    select_pane,
)


def test_parse_stat_ppid_handles_spaces_and_parens_in_comm() -> None:
    assert parse_stat_ppid("14501 (herdr) S 13352 14501 13352 0") == 13352
    assert parse_stat_ppid("77 (weird ) name) R 5 77 77") == 5
    assert parse_stat_ppid("garbage") is None


@pytest.mark.parametrize(
    ("argv", "session"),
    [
        (["herdr"], "default"),
        (["/home/u/.local/bin/herdr"], "default"),
        (["herdr", "--session", "work"], "work"),
        (["herdr", "--session=work"], "work"),
        (["herdr", "session", "attach", "work"], "work"),
        (["herdr", "--session", "x", "session", "attach", "work"], "work"),
        (["herdr", "--session", "work", "server"], None),
        (["herdr", "pane", "list"], None),
        (["herdr", "--remote", "host"], None),
        (["herdr", "--machine=box", "--session", "w"], None),
        (["fish"], None),
        ([], None),
    ],
)
def test_parse_client_session(argv: list[str], session: str | None) -> None:
    assert parse_client_session(argv) == session


def test_descendants() -> None:
    ppids = {2: 1, 3: 2, 4: 3, 5: 1, 9: 8}
    assert descendants(1, ppids) == {2, 3, 4, 5}
    assert descendants(8, ppids) == {9}


def test_herdr_client_sessions_ignores_server_and_other_trees() -> None:
    procs = {
        6899: (1, ["ghostty"]),
        13349: (6899, ["login"]),
        13352: (13349, ["fish"]),
        14501: (13352, ["herdr", "session", "attach", "work"]),
        3131: (1, ["herdr", "--session", "work", "server"]),
        5000: (1, ["herdr", "--session", "other"]),
    }
    assert herdr_client_sessions(6899, procs) == ["work"]
    assert herdr_client_sessions(4242, procs) == []


def test_choose_session() -> None:
    assert choose_session(["work"], 1) == ("work", None)
    assert choose_session([], 1) == (None, "janela focada não tem herdr")
    assert choose_session(["work"], 2) == (None, "várias janelas do terminal")
    assert choose_session(["a", "b"], 1) == (None, "várias sessões herdr na janela")


def _panes(*panes: dict) -> dict:
    return {"result": {"panes": list(panes)}}


def test_select_pane_focused_agent() -> None:
    target, reason = select_pane(
        _panes(
            {"pane_id": "w:p1", "focused": False, "agent": "claude", "label": "other"},
            {"pane_id": "w:p2", "focused": True, "agent": "claude", "label": "x" * 60},
        ),
        "work",
    )
    assert reason is None
    assert target is not None
    assert target["session"] == "work"
    assert target["pane_id"] == "w:p2"
    assert len(target["label"]) == 40
    assert target["label"].endswith("…")


def test_select_pane_refuses_shell_and_nothing_focused() -> None:
    shell = {"pane_id": "w:p3", "focused": True, "label": "fish"}
    assert select_pane(_panes(shell), "work") == (None, "painel focado não é agente")
    assert select_pane(_panes(), "work") == (None, "nenhum painel focado")


def test_normalize_text() -> None:
    assert normalize_text("  oi\n\ntudo  bem?\t ") == "oi tudo bem?"


def test_parse_herdr_output() -> None:
    assert parse_herdr_output('{"id":"x","result":{"panes":[]}}') == ({"panes": []}, None)
    assert parse_herdr_output('{"error":{"code":"server_not_running"}}') == (
        None,
        "server_not_running",
    )
    assert parse_herdr_output("not json") == (None, "invalid_response")


def test_reason_for() -> None:
    assert reason_for("agent_blocked") == "agente aguardando aprovação"
    assert reason_for("weird") == "erro do herdr (weird)"
