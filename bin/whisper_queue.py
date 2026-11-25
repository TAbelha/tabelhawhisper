"""On-disk transcription queue for tabelhawhisper.

Each finished recording becomes a job file ``/tmp/tabelhawhisper-queue/<id>.json``
(``id`` = recording start in epoch milliseconds, so names sort oldest first).
A single worker process, guarded by an flock on ``worker.lock``, drains the
queue in order. The pill reads ``/tmp/tabelhawhisper-queue.json``
(``{"pending": n}``) to show how many takes are still waiting.

The queue is deliberately separate from the recorder state file: the recorder
can start a new take while the worker is busy, and neither overwrites the other.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

QUEUE_DIR = Path("/tmp/tabelhawhisper-queue")
QUEUE_STATUS_PATH = Path("/tmp/tabelhawhisper-queue.json")
MAX_ATTEMPTS = 2  # a job whose worker died this many times is given up

_worker_lock_fd: int | None = None


def _atomic_write_json(path: Path, data: object) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, ensure_ascii=False)
        Path(tmp_path).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()
        raise


def _job_path(job_id: str) -> Path:
    return QUEUE_DIR / f"{job_id}.json"


def enqueue(job: dict) -> Path:
    """Write a job file (idempotent: re-enqueueing the same id replaces it)."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    path = _job_path(job["id"])
    _atomic_write_json(path, job)
    return path


def list_jobs() -> list[Path]:
    """Job files, oldest first."""
    if not QUEUE_DIR.is_dir():
        return []
    paths = [p for p in QUEUE_DIR.glob("*.json") if p.stem.isdigit()]
    return sorted(paths, key=lambda p: int(p.stem))


def read_job(path: Path) -> dict | None:
    """Parse a job file; None when it is missing, unreadable or malformed."""
    try:
        job = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(job, dict) or job.get("id") != path.stem:
        return None
    return job


def update_job(job: dict) -> None:
    _atomic_write_json(_job_path(job["id"]), job)


def remove_job(job: dict) -> None:
    """Delete the job file and its temporary wav (the saved copy is kept)."""
    _job_path(job["id"]).unlink(missing_ok=True)
    wav = job.get("wav")
    if wav:
        with contextlib.suppress(OSError):
            Path(wav).unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            Path(f"{wav}.part").unlink(missing_ok=True)


def clear_queue() -> None:
    for path in list_jobs():
        job = read_job(path)
        if job is None:
            path.unlink(missing_ok=True)
        else:
            remove_job(job)


def publish_status() -> int:
    """Recount the jobs and write the status file the pill reads."""
    lock_path = QUEUE_STATUS_PATH.with_suffix(".lock")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pending = len(list_jobs())
        _atomic_write_json(QUEUE_STATUS_PATH, {"pending": pending})
    return pending


def read_status() -> int:
    try:
        return int(json.loads(QUEUE_STATUS_PATH.read_text()).get("pending", 0))
    except (OSError, ValueError, AttributeError):
        return 0


def try_acquire_worker_lock() -> bool:
    """Take the single-worker lock without blocking; records our pid in it."""
    global _worker_lock_fd
    if _worker_lock_fd is not None:
        return True
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(QUEUE_DIR / "worker.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return False
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    _worker_lock_fd = fd
    return True


def release_worker_lock() -> None:
    global _worker_lock_fd
    fd = _worker_lock_fd
    if fd is None:
        return
    _worker_lock_fd = None
    with contextlib.suppress(OSError):
        os.ftruncate(fd, 0)
    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def worker_pid() -> int | None:
    """Pid written by the worker currently holding the lock, if any."""
    try:
        raw = (QUEUE_DIR / "worker.lock").read_text().strip()
    except OSError:
        return None
    return int(raw) if raw.isdigit() else None


def run_worker(
    process: Callable[[dict], None],
    give_up: Callable[[dict], None],
    log: Callable[[str], None] = lambda _msg: None,
) -> int:
    """Drain the queue oldest first. Returns how many jobs were handled.

    Returns 0 immediately when another worker holds the lock. ``attempts`` is
    persisted before processing, so a job whose worker was killed is retried by
    the next worker and given up after ``MAX_ATTEMPTS``.
    """
    if not try_acquire_worker_lock():
        return 0
    handled = 0
    try:
        while True:
            paths = list_jobs()
            if not paths:
                # A recorder may enqueue (and spawn a worker that finds the lock
                # still held) between our listing and the release: look again.
                release_worker_lock()
                if not list_jobs() or not try_acquire_worker_lock():
                    publish_status()
                    return handled
                continue
            path = paths[0]
            job = read_job(path)
            if job is None:
                log(f"queue: dropping malformed job {path.name}")
                path.unlink(missing_ok=True)
                publish_status()
                continue
            wav = job.get("wav")
            if not wav or not Path(wav).exists():
                log(f"queue: wav missing for job {job['id']}, dropping")
                remove_job(job)
                publish_status()
                continue
            job["attempts"] = int(job.get("attempts", 0)) + 1
            update_job(job)
            try:
                if job["attempts"] > MAX_ATTEMPTS:
                    give_up(job)
                else:
                    publish_status()
                    process(job)
            except Exception as e:
                log(f"queue: job {job['id']} failed: {e}")
            finally:
                remove_job(job)
                publish_status()
            handled += 1
    finally:
        release_worker_lock()
