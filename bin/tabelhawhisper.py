#!/usr/bin/env python3
"""tabelhawhisper orchestrator.

Two modes: wav (file-based, pause via SIGSTOP/SIGCONT) and streaming (pipe-based, no pause).

Recorder states (``/tmp/tabelhawhisper.json``):
idle -> recording <-> paused -> transcribing (only while the wav is finalized) -> idle.
In wav mode ``stop`` hands the finished take to the on-disk queue (``whisper_queue``)
and frees the recorder right away, so a new take can start while a single
background worker (``work``, procname ``twhisper-tx``) transcribes earlier ones.
The worker never writes the recorder state; the pill reads the queue count from
``/tmp/tabelhawhisper-queue.json``.

History persisted in ~/.config/tabelha/tabelhawhisper/history.json.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from whisper_core import (
    LEVELS_PATH,
    LevelMeter,
    load_config,
    pcm16_rms,
    read_state,
    resolve_save_dir,
    saved_recording_path,
    transcribe_file,
    write_history,
    write_levels,
    write_state,
)
from whisper_deliver import capture_target, deliver
from whisper_queue import (
    clear_queue,
    enqueue,
    publish_status,
    run_worker,
    update_job,
    worker_pid,
)

SCRIPT_DIR = Path(__file__).resolve().parent
PID_FILE = Path("/tmp/tabelhawhisper.pids")
LOG_FILE = Path("/tmp/tabelhawhisper.log")

MAX_LEVEL_SAMPLES = 60
WORKER_PROCNAME = "twhisper-tx"
FINALIZE_TIMEOUT_S = 3.0
START_FAILED_TEXT = "não foi possível iniciar a gravação (microfone/PipeWire indisponível)"


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


def _cont(pids: list[int]) -> None:
    """Wake stopped (paused) processes so they can act on the signals that follow."""
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGCONT)


def _kill(pids: list[int]) -> None:
    _cont(pids)
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGINT)
    time.sleep(0.4)
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)


def _kill_force(pids: list[int]) -> None:
    _cont(pids)
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


def _wav_writer(pipe, wav_path: str) -> None:
    """Read PCM from the pipe into ``<wav>.part``; rename to ``wav_path`` at EOF.

    The rename tells ``stop`` (another process) that the header is final.
    """
    import wave

    part = f"{wav_path}.part"
    with wave.open(part, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # s16le
        wf.setframerate(16000)
        meter = LevelMeter(MAX_LEVEL_SAMPLES)
        while True:
            data = pipe.read(4096)
            if not data:
                break
            wf.writeframes(data)
            with contextlib.suppress(Exception):
                write_levels(meter.push(pcm16_rms(data)))
    Path(part).replace(wav_path)


def _finalize_wav(wav_path: str, timeout_s: float = FINALIZE_TIMEOUT_S) -> bool:
    """Wait for the writer thread (in the ``start`` process) to rename the wav."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if Path(wav_path).exists():
            return True
        time.sleep(0.05)
    return Path(wav_path).exists()


def save_recording(wav_path: str, cfg: dict, start_ts: float) -> str | None:
    """Copy the take to the recordings dir when ``save_audio = true``."""
    directory = resolve_save_dir(cfg)
    if directory is None:
        return None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        dest = saved_recording_path(directory, start_ts)
        shutil.copy2(wav_path, dest)
    except OSError as e:
        log(f"save_recording failed: {e}")
        return None
    return str(dest)


def resolve_send(cli: bool | None, at_start: bool | None, cfg_default: object) -> bool:
    """Stop-time flag > start-time flag > ``send_to_agent`` config."""
    for value in (cli, at_start):
        if value is not None:
            return bool(value)
    return cfg_default is True


def _clear_levels() -> None:
    with contextlib.suppress(Exception):
        LEVELS_PATH.unlink(missing_ok=True)


def _kick_worker() -> None:
    """Spawn a worker; it exits at once if another one already holds the lock."""
    _spawn([sys.executable, str(SCRIPT_DIR / "tabelhawhisper.py"), "work"])


def start(cfg: dict, send: bool | None = None) -> None:
    state = read_state()
    if state.get("state") in ("recording", "paused") and is_recording():
        log("start: already recording, ignored")
        return
    start_ts = time.time()
    wav = f"/tmp/tabelhawhisper-{time.time_ns() // 1_000_000}.wav"
    mode = cfg.get("mode", "wav")
    write_state(
        {
            "state": "recording",
            "start": start_ts,
            "paused_at": None,
            "text": "",
            "mode": mode,
            "wav": wav,
            "send": send,
            "python": sys.executable,
            "script": str(SCRIPT_DIR / "tabelhawhisper.py"),
        }
    )
    log(f"start mode={mode} wav={wav} send={send}")

    pw = subprocess.Popen(
        [
            "pw-record",
            "--raw",
            "--media-category",
            "Capture",
            "--format",
            "s16",
            "--rate",
            "16000",
            "--channels",
            "1",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    if mode == "wav":
        writer = threading.Thread(target=_wav_writer, args=(pw.stdout, wav), daemon=True)
        writer.start()
        pids = [pw.pid]
    else:
        st = subprocess.Popen(
            [sys.executable, str(SCRIPT_DIR / "whisper_stream.py")],
            stdin=pw.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if pw.stdout is not None:
            pw.stdout.close()
        writer = None
        pids = [pw.pid, st.pid]

    PID_FILE.write_text(json.dumps({"pids": pids, "mode": mode}))
    time.sleep(0.5)
    live = find_pwrec()
    log(f"after start pwrec_alive={live}")
    if not live:
        write_state({"state": "error", "text": START_FAILED_TEXT}, expect={"wav": wav})
        PID_FILE.unlink(missing_ok=True)
        return
    if writer is not None:
        writer.join()  # blocks until pw-record is killed (stop) and the pipe closes


def pause(cfg: dict) -> None:
    """SIGSTOP the pw-record process(es), state -> paused (wav mode only)."""
    state = read_state()
    if state.get("state") != "recording" or state.get("mode") != "wav":
        return
    pids = _read_pids()
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGSTOP)
    write_state({"state": "paused", "paused_at": time.time()})
    log("pause: SIGSTOP sent")


def resume(cfg: dict) -> None:
    """SIGCONT the pw-record process(es), state -> recording."""
    state = read_state()
    if state.get("state") != "paused":
        return
    _cont(_read_pids())
    # Shift start forward by the paused span so elapsed (now - start) excludes it.
    patch: dict = {"state": "recording", "paused_at": None}
    paused_at = state.get("paused_at")
    if isinstance(paused_at, int | float) and isinstance(state.get("start"), int | float):
        patch["start"] = state["start"] + max(0.0, time.time() - paused_at)
    write_state(patch)
    log("resume: SIGCONT sent")


def stop(cfg: dict, send: bool | None = None) -> None:
    """End the current take; in wav mode queue it and free the recorder."""
    state = read_state()
    cur = state.get("state", "idle")
    if cur not in ("recording", "paused"):
        orphans = find_pwrec()
        if orphans and cur != "transcribing":
            log(f"stop: killing orphan pw-record {orphans} (state={cur})")
            _kill(orphans)
            PID_FILE.unlink(missing_ok=True)
        return
    mode = state.get("mode", "wav")
    wav = state.get("wav")
    # Claim the stop: a second concurrent stop (double key press) sees the new state.
    if write_state({"state": "transcribing"}, expect={"state": cur, "wav": wav}) is None:
        log("stop: lost the race to another stop")
        return

    target, target_error = None, None
    if resolve_send(send, state.get("send"), cfg.get("send_to_agent")):
        target, target_error = capture_target()
        log(f"stop: send target={target} error={target_error}")

    pids = sorted(set(find_pwrec()) | set(_read_pids()))
    log(f"stop killing pids={pids} mode={mode}")
    _kill(pids)
    PID_FILE.unlink(missing_ok=True)

    if mode == "streaming":
        text = read_state().get("text", "")
        write_state({"state": "idle", "text": ""}, expect={"wav": wav})
        _clear_levels()
        sent_to, send_error = _deliver_text(text, target, target_error, already=False)
        _finish(text, cfg, mode=mode, wav_path=None, sent_to=sent_to, send_error=send_error)
        log(f"stop streaming done textlen={len(text)}")
        return

    if not wav or not _finalize_wav(wav):
        log(f"stop: wav never finalized ({wav})")
        write_state({"state": "error", "text": "gravação perdida"}, expect={"wav": wav})
        _clear_levels()
        return

    start_ts = state.get("start")
    start_ts = float(start_ts) if isinstance(start_ts, int | float) else time.time()
    job = {
        "id": Path(wav).stem.rsplit("-", 1)[-1],
        "wav": wav,
        "saved": save_recording(wav, cfg, start_ts),
        "start": start_ts,
        "mode": mode,
        "attempts": 0,
        "send": target is not None or target_error is not None,
        "target": target,
        "target_error": target_error,
        "delivered": False,
    }
    enqueue(job)
    publish_status()
    write_state({"state": "idle", "text": ""}, expect={"wav": wav})
    _clear_levels()
    _kick_worker()
    log(f"stop queued job={job['id']} saved={job['saved']}")


def _deliver_text(
    text: str, target: dict | None, target_error: str | None, *, already: bool
) -> tuple[str | None, str | None]:
    """(sent_to label, send error) for a finished transcript."""
    if not text.strip() or (target is None and target_error is None):
        return None, None
    if target is None:
        return None, target_error
    if already:
        return target.get("label"), None
    err = deliver(target, text)
    return (target.get("label"), None) if err is None else (None, err)


def _finish(
    text: str,
    cfg: dict,
    *,
    mode: str,
    wav_path: str | None,
    sent_to: str | None = None,
    send_error: str | None = None,
) -> None:
    """History, clipboard and notification for a finished transcript."""
    entry: dict = {
        "ts": int(time.time()),
        "mode": mode,
        "state": "done",
        "text": text,
        "wav_path": wav_path,
    }
    if sent_to:
        entry["sent_to"] = sent_to
    if send_error:
        entry["send_error"] = send_error
    write_history(entry, cfg.get("history_size", 100))
    if not text.strip():
        return
    # A failed delivery always leaves the text on the clipboard so it is not lost.
    if cfg.get("copy_clipboard") or send_error:
        _clipboard_store(text)
    if sent_to:
        _notify(f"Enviado para {sent_to}\n{text}")
    elif send_error:
        _notify(f"não enviado: {send_error}\n{text}")
    else:
        _notify(text)


def _history_error(cfg: dict, job: dict, message: str) -> None:
    write_history(
        {
            "ts": int(time.time()),
            "mode": job.get("mode"),
            "state": "error",
            "text": f"[erro: {message}]",
            "wav_path": job.get("saved"),
        },
        cfg.get("history_size", 100),
    )
    _notify(f"erro na transcrição: {message}")


def _process_job(job: dict, cfg: dict) -> None:
    log(f"work: transcribing job={job['id']} attempt={job.get('attempts')}")
    try:
        text = transcribe_file(
            job["wav"],
            cfg["model"],
            cfg["language"],
            cfg.get("device", "cpu"),
            cfg.get("multilingual", True),
            cfg.get("beam_size", 5),
        )
    except Exception as e:
        log(f"work: transcribe error job={job['id']}: {e}")
        _history_error(cfg, job, str(e))
        return
    already = bool(job.get("delivered"))
    sent_to, send_error = _deliver_text(
        text, job.get("target"), job.get("target_error"), already=already
    )
    if sent_to and not already:
        job["delivered"] = True  # a retry after a crash must not submit twice
        update_job(job)
    _finish(
        text,
        cfg,
        mode=job.get("mode", "wav"),
        wav_path=job.get("saved"),
        sent_to=sent_to,
        send_error=send_error,
    )
    log(f"work: done job={job['id']} textlen={len(text)} sent_to={sent_to} err={send_error}")


def _give_up(job: dict, cfg: dict) -> None:
    log(f"work: giving up job={job['id']} after {job.get('attempts')} attempts")
    _history_error(cfg, job, "a transcrição falhou repetidamente")


def work() -> None:
    """Queue worker: transcribe pending takes oldest first, then exit."""
    _set_procname(WORKER_PROCNAME)
    cfg = load_config()
    handled = run_worker(lambda job: _process_job(job, cfg), lambda job: _give_up(job, cfg), log)
    log(f"work: exit handled={handled}")


def cancel_recording(cfg: dict) -> None:
    """Discard the take being recorded; queued takes keep going."""
    state = read_state()
    cur = state.get("state", "idle")
    pids = sorted(set(find_pwrec()) | set(_read_pids()))
    if cur not in ("recording", "paused") and not pids:
        return
    log(f"cancel-recording killing pids={pids} state={cur}")
    _kill_force(pids)
    PID_FILE.unlink(missing_ok=True)
    wav = state.get("wav")
    if wav and state.get("mode", "wav") == "wav":
        _finalize_wav(wav, timeout_s=1.0)  # let the writer rename, then delete both
        for path in (wav, f"{wav}.part"):
            with contextlib.suppress(OSError):
                Path(path).unlink(missing_ok=True)
    write_state({"state": "idle", "text": ""}, expect={"wav": wav})
    _clear_levels()
    log("cancel-recording done")


def _is_worker(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip() == WORKER_PROCNAME
    except OSError:
        return False


def cancel_queue(cfg: dict) -> None:
    """Drop every queued take and stop the worker; the recorder is untouched."""
    clear_queue()
    pid = worker_pid()
    if pid and _is_worker(pid):
        log(f"cancel-queue killing worker pid={pid}")
        _kill_force([pid])
    publish_status()
    if read_state().get("state") == "transcribing":
        write_state({"state": "idle", "text": ""}, expect={"state": "transcribing"})
    log("cancel-queue done")


def cancel(cfg: dict) -> None:
    """Cancel whatever the pill shows: the recording if any, else the queue."""
    if read_state().get("state") in ("recording", "paused") or find_pwrec():
        cancel_recording(cfg)
    else:
        cancel_queue(cfg)


def toggle(cfg: dict, send: bool | None = None) -> None:
    """Start or stop recording. Never cancels: queued takes always finish."""
    cur = read_state().get("state", "idle")
    rec = is_recording()
    log(f"toggle state={cur} is_recording={rec} send={send}")
    if cur in ("recording", "paused") or (rec and cur != "transcribing"):
        stop(cfg, send)
    else:
        start(cfg, send)


def main() -> None:
    _set_procname("twhisper")
    ap = argparse.ArgumentParser(prog="tabelhawhisper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("toggle", "start", "stop"):
        sp = sub.add_parser(name)
        sp.add_argument(
            "--send",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="submit the transcript to the focused herdr agent pane",
        )
    for name in ("pause", "resume", "cancel", "cancel-recording", "cancel-queue", "work"):
        sub.add_parser(name)
    args = ap.parse_args()

    cfg = load_config()
    send = getattr(args, "send", None)
    if args.cmd == "toggle":
        toggle(cfg, send)
    elif args.cmd == "start":
        start(cfg, send)
    elif args.cmd == "stop":
        stop(cfg, send)
    elif args.cmd == "pause":
        pause(cfg)
    elif args.cmd == "resume":
        resume(cfg)
    elif args.cmd == "cancel":
        cancel(cfg)
    elif args.cmd == "cancel-recording":
        cancel_recording(cfg)
    elif args.cmd == "cancel-queue":
        cancel_queue(cfg)
    elif args.cmd == "work":
        work()


if __name__ == "__main__":
    main()
