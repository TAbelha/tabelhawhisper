#!/usr/bin/env python3
"""tabelhawhisper orchestrator (v2.0).

Two modes: wav (file-based, pausa via SIGSTOP/SIGCONT) and streaming (pipe-based, no pausa).
States: idle -> recording -> paused -> recording -> transcribing -> done -> idle.
Levels computed from PCM chunks, written to dedicated file (thread-safe).
History persisted in ~/.config/tabelha/whisper-dictate/history.json.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

from whisper_core import (
    LEVELS_PATH,
    load_config,
    read_state,
    rms_to_level,
    transcribe_file,
    write_history,
    write_levels,
    write_state,
)

SCRIPT_DIR = Path(__file__).resolve().parent
PID_FILE = Path("/tmp/whisper-dictate.pids")
LOG_FILE = Path("/tmp/whisper-dictate.log")

MAX_LEVEL_SAMPLES = 60


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


def _kill_force(pids: list[int]) -> None:
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGINT)
    time.sleep(0.3)
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
    time.sleep(0.3)
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


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
    """Return pids of actually-running pw-record processes for our session."""
    pids: list[int] = []
    proc = Path("/proc")
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except Exception:
            continue
        if cmd.startswith("pw-record") and "Capture" in cmd:
            with contextlib.suppress(ValueError):
                pids.append(int(d.name))
    return pids


def is_recording() -> bool:
    running = find_pwrec()
    return bool(running) or bool([p for p in _read_pids() if _alive(p)])


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
                "TAbelhaWhisper",
                "Transcrição",
                text[:500],
            ],
            check=False,
        )
    except Exception as e:
        log(f"notify failed: {e}")


def _clipboard_store(text: str) -> None:
    """Copy text to the system clipboard via wl-copy."""
    subprocess.run(["wl-copy"], input=text.encode(), check=False)


def _set_procname(name: str) -> None:
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.prctl.argtypes = [ctypes.c_int, ctypes.c_char_p]
        libc.prctl.restype = ctypes.c_int
        libc.prctl(15, name.encode()[:15])  # PR_SET_NAME
    except Exception:
        pass


def _wav_writer(pipe, wav_path: str, start_ts: int) -> None:
    """Read PCM from pipe, write wav, compute levels to dedicated file."""
    import wave

    sample_rate = 16000
    channels = 1
    sample_width = 2  # s16le

    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)

        levels: list[float] = []

        while True:
            data = pipe.read(4096)
            if not data:
                break
            wf.writeframes(data)

            samples = struct.unpack(f"<{len(data) // 2}h", data)
            rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
            level = rms_to_level(rms)
            levels.append(level)
            levels = levels[-MAX_LEVEL_SAMPLES:]

            with contextlib.suppress(Exception):
                write_levels(levels)


def start(cfg: dict) -> None:
    ts = int(time.time())
    wav = f"/tmp/whisper-dictate-{ts}.wav"
    mode = cfg.get("mode", "wav")
    write_state(
        {
            "state": "recording",
            "start": ts,
            "text": "",
            "mode": mode,
            "wav": wav,
            "python": sys.executable,
            "script": str(SCRIPT_DIR / "whisper_dictate.py"),
        }
    )
    log(f"start mode={mode} wav={wav}")

    pw = subprocess.Popen(
        ["pw-record", "--raw", "--media-category", "Capture", "--format", "s16", "--rate", "16000", "--channels", "1", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    if mode == "wav":
        writer = threading.Thread(target=_wav_writer, args=(pw.stdout, wav, ts), daemon=True)
        writer.start()
        pids = [pw.pid]
        PID_FILE.write_text(json.dumps({"pids": pids, "mode": mode}))
        time.sleep(0.5)
        live = find_pwrec()
        log(f"after start pwrec_alive={live}")
        if not live:
            write_state(
                {
                    "state": "error",
                    "text": "não foi possível iniciar a gravação (microfone/PipeWire indisponível)",
                }
            )
            PID_FILE.unlink(missing_ok=True)
            return
        writer.join()  # block until pw-record is killed (stop) → pipe closes
        return
    else:  # streaming
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

    PID_FILE.write_text(json.dumps({"pids": pids, "mode": mode}))
    time.sleep(0.5)
    live = find_pwrec()
    log(f"after start pwrec_alive={live}")
    if not live:
        write_state(
            {
                "state": "error",
                "text": "não foi possível iniciar a gravação (microfone/PipeWire indisponível)",
            }
        )
        PID_FILE.unlink(missing_ok=True)


def pause(cfg: dict) -> None:
    """SIGSTOP the pw-record process(es), state -> paused (wav mode only)."""
    state = read_state()
    if state.get("state") != "recording" or state.get("mode") != "wav":
        return
    pids = _read_pids()
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGSTOP)
    write_state({"state": "paused"})
    log("pause: SIGSTOP sent")


def resume(cfg: dict) -> None:
    """SIGCONT the pw-record process(es), state -> recording."""
    state = read_state()
    if state.get("state") != "paused":
        return
    pids = _read_pids()
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGCONT)
    write_state({"state": "recording"})
    log("resume: SIGCONT sent")


def stop(cfg: dict) -> None:
    state = read_state()
    mode = state.get("mode", "wav")
    wav = state.get("wav")
    pids = sorted(set(find_pwrec()) | set(_read_pids()))
    log(f"stop killing pids={pids} mode={mode}")
    _kill(pids)
    PID_FILE.unlink(missing_ok=True)

    if mode == "wav":
        write_state({"state": "transcribing"})
        tx_pid = _spawn(
            [sys.executable, str(SCRIPT_DIR / "whisper_dictate.py"), "transcribe", wav]
        )
        PID_FILE.write_text(json.dumps({"pids": [tx_pid], "mode": mode}))
        log(f"stop spawned transcribe pid={tx_pid} wav={wav}")
    elif mode == "streaming":
        final = read_state()
        text = final.get("text", "")
        _finish(text, cfg)
        log(f"stop streaming done textlen={len(text)}")


def _finish(text: str, cfg: dict) -> None:
    """Write result to history, clipboard, notification, and clear levels."""
    state = read_state()
    write_state({"state": "done", "text": text})
    write_history(
        {
            "ts": int(time.time()),
            "mode": state.get("mode"),
            "state": "done",
            "text": text,
            "wav_path": state.get("wav"),
        },
        cfg.get("history_size", 100),
    )
    if text.strip():
        if cfg.get("copy_clipboard"):
            _clipboard_store(text)
        _notify(text)
    # Clear levels
    with contextlib.suppress(Exception):
        LEVELS_PATH.unlink(missing_ok=True)


def cancel(cfg: dict) -> None:
    """Kill any running transcription/recording and reset to idle."""
    state = read_state()
    cur_state = state.get("state", "idle")
    if cur_state == "idle":
        return

    pids = sorted(set(find_pwrec()) | set(_read_pids()))
    log(f"cancel killing pids={pids} state={cur_state}")
    _kill_force(pids)
    PID_FILE.unlink(missing_ok=True)

    wav = state.get("wav")
    if wav:
        with contextlib.suppress(OSError):
            Path(wav).unlink(missing_ok=True)

    write_state({"state": "idle", "text": ""})
    with contextlib.suppress(Exception):
        LEVELS_PATH.unlink(missing_ok=True)
    log("cancel done")


def transcribe(wav_path: str) -> None:
    """Transcribe a wav file and write the result to the state file."""
    _set_procname("twhisper-tx")
    cfg = load_config()
    write_state({"state": "transcribing"})
    log(f"transcribe start wav={wav_path}")
    try:
        text = transcribe_file(
            wav_path,
            cfg["model"],
            cfg["language"],
            cfg.get("device", "cpu"),
            cfg.get("multilingual", True),
            cfg.get("beam_size", 5),
        )
    except Exception as e:
        log(f"transcribe error: {e}")
        write_state({"state": "error", "text": f"[error: {e}]"})
        write_history(
            {
                "ts": int(time.time()),
                "mode": read_state().get("mode"),
                "state": "error",
                "text": f"[error: {e}]",
                "wav_path": wav_path,
            },
            cfg.get("history_size", 100),
        )
        return
    _finish(text, cfg)
    log(f"transcribe done textlen={len(text)}")


def toggle(cfg: dict) -> None:
    state = read_state()
    cur_state = state.get("state", "idle")
    rec = is_recording()
    log(f"toggle state={cur_state} is_recording={rec}")
    if rec or cur_state in ("recording", "paused"):
        stop(cfg)
    elif cur_state == "transcribing":
        cancel(cfg)
        cfg["mode"] = cfg.get("mode", "wav")
        start(cfg)
    else:
        cfg["mode"] = cfg.get("mode", "wav")
        start(cfg)


def main() -> None:
    _set_procname("twhisper")
    ap = argparse.ArgumentParser(prog="whisper_dictate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("toggle")
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("cancel")
    sub.add_parser("pause")
    sub.add_parser("resume")
    tp = sub.add_parser("transcribe")
    tp.add_argument("wav")
    args = ap.parse_args()

    cfg = load_config()
    if args.cmd == "toggle":
        toggle(cfg)
    elif args.cmd == "start":
        cfg["mode"] = cfg.get("mode", "wav")
        start(cfg)
    elif args.cmd == "stop":
        stop(cfg)
    elif args.cmd == "cancel":
        cancel(cfg)
    elif args.cmd == "pause":
        pause(cfg)
    elif args.cmd == "resume":
        resume(cfg)
    elif args.cmd == "transcribe":
        transcribe(args.wav)


if __name__ == "__main__":
    main()
