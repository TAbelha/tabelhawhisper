#!/usr/bin/env python3
"""tabelhawhisper orchestrator.

Run by the niri keybind (Mod+E). ``toggle`` starts or stops a recording; the
resulting transcript is written to the shared state file and copied to the
clipboard. On completion a low-priority, silent desktop notification is shown
(via notify-send); the dms bar widget and floating pill are the live feedback.

Transcription runs in a detachable child process so the dms pill (and the keybind
wrapper) can ``cancel`` it at any time without waiting for the model to finish.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from whisper_core import load_config, read_state, transcribe_file, write_state

SCRIPT_DIR = Path(__file__).resolve().parent
PID_FILE = Path("/tmp/whisper-dictate.pids")
LOG_FILE = Path("/tmp/whisper-dictate.log")


def log(msg: str) -> None:
    try:
        with LOG_FILE.open("a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _spawn(cmd: list[str]) -> int:
    p = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return p.pid


def _kill(pids: list[int]) -> None:
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGINT)
    time.sleep(0.4)
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)


def _read_pids() -> list[int]:
    try:
        return json.loads(PID_FILE.read_text()).get("pids", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def find_pwrec() -> list[int]:
    """Return pids of actually-running pw-record processes for our wav.

    Scans /proc directly so it works regardless of PATH or pid-file state
    (the pid file can go out of sync if a previous toggle crashed).
    """
    pids: list[int] = []
    proc = Path("/proc")
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except Exception:
            continue
        if cmd.startswith("pw-record") and "/tmp/whisper-dictate" in cmd:
            with contextlib.suppress(ValueError):
                pids.append(int(d.name))
    return pids


def is_recording() -> bool:
    running = find_pwrec()
    log(f"is_recording -> pwrec_pids={running} pidfile={_read_pids()}")
    return bool(running) or bool([p for p in _read_pids() if _alive(p)])


def start(cfg: dict) -> None:
    ts = int(time.time())
    wav = f"/tmp/whisper-dictate-{ts}.wav"
    mode = cfg["live_mode"]
    write_state({
        "state": "recording",
        "start": ts,
        "text": "",
        "mode": mode,
        "wav": wav,
        "python": sys.executable,
        "script": str(SCRIPT_DIR / "whisper_dictate.py"),
        "indicator": cfg.get("indicator", True),
    })
    log(f"start mode={mode} wav={wav}")

    pids: list[int] = []
    if mode == "streaming":
        pw = subprocess.Popen(
            ["pw-record", "--format", "s16", "--rate", "16000", "--channels", "1", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        st = subprocess.Popen(
            [sys.executable, str(SCRIPT_DIR / "whisper_stream.py")],
            stdin=pw.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if pw.stdout is not None:
            pw.stdout.close()
        pids = [pw.pid, st.pid]
    else:
        pids = [_spawn(["pw-record", "--format", "s16", "--rate", "16000", "--channels", "1", wav])]
        if mode == "partial":
            pids.append(
                _spawn(
                    [
                        sys.executable,
                        str(SCRIPT_DIR / "whisper_dictate.py"),
                        "watch",
                        wav,
                        str(cfg["partial_interval"]),
                    ]
                )
            )

    PID_FILE.write_text(json.dumps({"pids": pids, "mode": mode}))
    time.sleep(0.5)
    live = find_pwrec()
    log(f"after start pwrec_alive={live}")
    if not live:
        write_state(
            {
                "state": "error",
                "text": "nao foi possivel iniciar a gravacao (microfone/PipeWire indisponivel)",
            }
        )
        PID_FILE.unlink(missing_ok=True)


def _notify(text: str) -> None:
    try:
        subprocess.run(
            [
                "notify-send",
                "-u",
                "low",
                "-h",
                "boolean:suppress-sound:true",
                "-a",
                "TAbelha Whisper",
                "Transcrição",
                text[:500],
            ],
            check=False,
        )
    except Exception as e:
        log(f"notify failed: {e}")


def _set_procname(name: str) -> None:
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.prctl.argtypes = [ctypes.c_int, ctypes.c_char_p]
        libc.prctl.restype = ctypes.c_int
        libc.prctl(15, name.encode()[:15])  # PR_SET_NAME
    except Exception as e:
        log(f"set_procname failed: {e}")


def stop(cfg: dict) -> None:
    mode = read_state().get("mode") or cfg["live_mode"]
    wav = read_state().get("wav", cfg.get("wav"))
    pids = sorted(set(find_pwrec()) | set(_read_pids()))
    log(f"stop killing pids={pids} mode={mode}")
    _kill(pids)
    PID_FILE.unlink(missing_ok=True)

    if mode in ("off", "partial"):
        write_state({"state": "transcribing"})
        tx_pid = _spawn(
            [sys.executable, str(SCRIPT_DIR / "whisper_dictate.py"), "transcribe", wav]
        )
        PID_FILE.write_text(json.dumps({"pids": [tx_pid], "mode": mode}))
        log(f"stop spawned transcribe pid={tx_pid} wav={wav}")
    elif mode == "streaming":
        final = read_state()
        text = final.get("text", "")
        write_state({"state": "done", "text": text})
        if text.strip():
            if cfg.get("copy_clipboard"):
                subprocess.run(["wl-copy"], input=text.encode(), check=False)
            _notify(text)
        log(f"stop streaming done textlen={len(text)}")


def watch(wav: str, interval: int) -> None:
    """Partial mode: re-transcribe the growing wav until recording stops."""
    cfg = load_config()
    while read_state().get("state") == "recording":
        try:
            text = transcribe_file(
                wav,
                cfg["model"],
                cfg["language"],
                cfg.get("device", "cpu"),
                cfg.get("multilingual", True),
                cfg.get("beam_size", 5),
            )
            write_state({"text": text})
        except Exception:
            pass
        time.sleep(max(1, interval))


def toggle(cfg: dict) -> None:
    state = read_state()
    cur_state = state.get("state", "idle")
    rec = is_recording()
    log(f"toggle state={cur_state} is_recording={rec}")
    if rec or cur_state == "recording":
        stop(cfg)
    elif cur_state == "transcribing":
        cancel(cfg)
        start(cfg)
    else:
        start(cfg)


def main() -> None:
    _set_procname("twhisper")
    ap = argparse.ArgumentParser(prog="whisper_dictate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("toggle")
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("cancel")
    tp = sub.add_parser("transcribe")
    tp.add_argument("wav")
    wp = sub.add_parser("watch")
    wp.add_argument("wav")
    wp.add_argument("interval", type=int)
    args = ap.parse_args()

    cfg = load_config()
    if args.cmd == "toggle":
        toggle(cfg)
    elif args.cmd == "start":
        start(cfg)
    elif args.cmd == "stop":
        stop(cfg)
    elif args.cmd == "cancel":
        cancel(cfg)
    elif args.cmd == "transcribe":
        transcribe(args.wav)
    elif args.cmd == "watch":
        watch(args.wav, args.interval)


if __name__ == "__main__":
    main()
