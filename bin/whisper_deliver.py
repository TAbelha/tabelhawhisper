"""Deliver a transcript to the herdr agent pane that was focused at stop time.

Target resolution (``capture_target``), run when the recording is stopped:

1. ``niri msg --json focused-window`` gives the focused window's pid.
2. herdr *client* processes descended from that pid give the herdr session.
3. ``herdr --session S pane list`` gives the focused pane of that session.
4. The pane must run an agent (``agent`` set); shells and editors are refused.

herdr's ``focused`` flag is per session and ignores OS focus, which is why the
niri window comes first. Terminals that run every window in one process (Ghostty)
cannot be mapped window -> client, so several windows sharing the pid is refused.

``deliver`` later submits the text with ``herdr agent prompt`` (types it and
presses Enter in that pane, without focusing it).

Everything here returns a Portuguese reason string on failure instead of raising:
the caller falls back to the clipboard and shows "não enviado: <motivo>".
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

LABEL_MAX = 40

REASONS = {
    "agent_blocked": "agente aguardando aprovação",
    "server_not_running": "sessão herdr parada",
    "timeout": "herdr não respondeu a tempo",
    "herdr_missing": "herdr não encontrado",
    "niri_missing": "niri não encontrado",
    "invalid_response": "resposta inválida do herdr",
    "pane_not_found": "painel não existe mais",
}


def reason_for(code: str) -> str:
    return REASONS.get(code, f"erro do herdr ({code})")


# ---------------------------------------------------------------- pure parsers


def parse_stat_ppid(stat: str) -> int | None:
    """Parent pid from a ``/proc/<pid>/stat`` line (comm may contain spaces/parens)."""
    _, sep, rest = stat.rpartition(")")
    if not sep:
        return None
    fields = rest.split()
    if len(fields) < 2 or not fields[1].isdigit():
        return None
    return int(fields[1])


def parse_client_session(argv: list[str]) -> str | None:
    """herdr session a process is attached to as a *client*, or None.

    Accepted: ``herdr``, ``herdr --session S``, ``herdr session attach S``.
    The server (``herdr --session S server``), other subcommands and remote
    clients are not local clients and give None.
    """
    if not argv or Path(argv[0]).name != "herdr":
        return None
    session = "default"
    rest: list[str] = []
    args = argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--remote", "--machine") or arg.startswith(("--remote=", "--machine=")):
            return None
        if arg == "--session" and i + 1 < len(args):
            session = args[i + 1]
            i += 2
            continue
        if arg.startswith("--session="):
            session = arg.split("=", 1)[1]
        else:
            rest.append(arg)
        i += 1
    if not rest:
        return session
    if len(rest) == 3 and rest[0] == "session" and rest[1] == "attach":
        return rest[2]
    return None


def descendants(root: int, ppids: dict[int, int]) -> set[int]:
    children: dict[int, list[int]] = {}
    for pid, ppid in ppids.items():
        children.setdefault(ppid, []).append(pid)
    found: set[int] = set()
    stack = [root]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def herdr_client_sessions(root: int, procs: dict[int, tuple[int, list[str]]]) -> list[str]:
    """Distinct herdr sessions with a client process under ``root``."""
    under = descendants(root, {pid: ppid for pid, (ppid, _) in procs.items()})
    sessions = {parse_client_session(procs[pid][1]) for pid in under}
    return sorted(s for s in sessions if s)


def choose_session(clients: list[str], same_pid_windows: int) -> tuple[str | None, str | None]:
    """(session, None) or (None, reason)."""
    if not clients:
        return None, "janela focada não tem herdr"
    if same_pid_windows > 1:
        return None, "várias janelas do terminal"
    if len(clients) > 1:
        return None, "várias sessões herdr na janela"
    return clients[0], None


def select_pane(pane_list: dict, session: str) -> tuple[dict | None, str | None]:
    """Focused agent pane from ``herdr pane list`` JSON as a target dict."""
    panes = (pane_list.get("result") or {}).get("panes") or []
    focused = [p for p in panes if isinstance(p, dict) and p.get("focused")]
    if not focused:
        return None, "nenhum painel focado"
    pane = focused[0]
    agent = pane.get("agent")
    if not agent or not pane.get("pane_id"):
        return None, "painel focado não é agente"
    label = str(pane.get("label") or agent)
    if len(label) > LABEL_MAX:
        label = label[: LABEL_MAX - 1] + "…"
    return {"session": session, "pane_id": pane["pane_id"], "agent": agent, "label": label}, None


def normalize_text(text: str) -> str:
    """One line: a newline would submit the prompt early in most agent TUIs."""
    return " ".join(text.split())


def parse_herdr_output(stdout: str) -> tuple[dict | None, str | None]:
    """(result, None) or (None, error code) from herdr's JSON reply."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None, "invalid_response"
    if not isinstance(data, dict):
        return None, "invalid_response"
    err = data.get("error")
    if isinstance(err, dict):
        return None, str(err.get("code") or "invalid_response")
    result = data.get("result")
    return (result if isinstance(result, dict) else {}), None


# ---------------------------------------------------------------- thin wrappers


def herdr_bin() -> str | None:
    found = shutil.which("herdr")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "herdr"
    return str(fallback) if fallback.exists() else None


def _run(argv: list[str], timeout: float) -> tuple[int, str]:
    proc = subprocess.run(
        argv, capture_output=True, text=True, timeout=max(timeout, 0.05), check=False
    )
    return proc.returncode, proc.stdout


def _read_procs() -> dict[int, tuple[int, list[str]]]:
    procs: dict[int, tuple[int, list[str]]] = {}
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            ppid = parse_stat_ppid((d / "stat").read_text())
            raw = (d / "cmdline").read_bytes()
        except OSError:
            continue
        if ppid is None:
            continue
        argv = [a.decode(errors="ignore") for a in raw.split(b"\x00") if a]
        procs[int(d.name)] = (ppid, argv)
    return procs


def capture_target(budget_s: float = 0.3) -> tuple[dict | None, str | None]:
    """Resolve the focused herdr agent pane. Never raises."""
    deadline = time.monotonic() + budget_s
    try:
        if not shutil.which("niri"):
            return None, reason_for("niri_missing")
        rc, out = _run(["niri", "msg", "--json", "focused-window"], deadline - time.monotonic())
        window = json.loads(out) if rc == 0 and out.strip() else None
        if not isinstance(window, dict) or not isinstance(window.get("pid"), int):
            return None, "nenhuma janela focada"
        pid = window["pid"]
        rc, out = _run(["niri", "msg", "--json", "windows"], deadline - time.monotonic())
        windows = json.loads(out) if rc == 0 else []
        same_pid = sum(1 for w in windows if isinstance(w, dict) and w.get("pid") == pid)

        session, reason = choose_session(herdr_client_sessions(pid, _read_procs()), same_pid)
        if session is None:
            return None, reason
        herdr = herdr_bin()
        if herdr is None:
            return None, reason_for("herdr_missing")
        _, out = _run([herdr, "--session", session, "pane", "list"], deadline - time.monotonic())
        result, code = parse_herdr_output(out)
        if result is None:
            return None, reason_for(code or "invalid_response")
        return select_pane({"result": result}, session)
    except subprocess.TimeoutExpired:
        return None, reason_for("timeout")
    except Exception as e:  # never break stop() over delivery
        return None, f"falha ao achar o painel ({e})"


def deliver(target: dict, text: str, timeout_s: float = 5.0) -> str | None:
    """Submit ``text`` to the target pane. Returns None on success, else a reason."""
    herdr = herdr_bin()
    if herdr is None:
        return reason_for("herdr_missing")
    line = normalize_text(text)
    if not line:
        return "transcrição vazia"
    argv = [herdr, "--session", target["session"], "agent", "prompt", target["pane_id"], line]
    try:
        rc, out = _run(argv, timeout_s)
    except subprocess.TimeoutExpired:
        return reason_for("timeout")
    except OSError as e:
        return f"falha ao executar herdr ({e})"
    # Success may print a JSON result or nothing; only an explicit error or a
    # non-zero exit counts as failure.
    _, code = parse_herdr_output(out) if out.strip() else (None, None)
    if code and code != "invalid_response":
        return reason_for(code)
    if rc != 0:
        return reason_for(code or "invalid_response")
    return None


if __name__ == "__main__":  # manual check: prints what Mod+Shift+E would target
    print(capture_target(budget_s=2.0))
