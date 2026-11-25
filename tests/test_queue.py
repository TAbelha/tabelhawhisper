from __future__ import annotations

import multiprocessing
from pathlib import Path

import whisper_queue as wq


def make_job(qdir: Path, job_id: int, **extra) -> dict:
    wav = qdir.parent / f"{job_id}.wav"
    wav.write_bytes(b"RIFF")
    job = {
        "id": str(job_id),
        "wav": str(wav),
        "saved": None,
        "start": job_id / 1000,
        "mode": "wav",
        "attempts": 0,
        **extra,
    }
    wq.enqueue(job)
    return job


def test_enqueue_is_idempotent(qpaths: Path) -> None:
    make_job(qpaths, 100)
    make_job(qpaths, 100)
    assert len(wq.list_jobs()) == 1


def test_jobs_sorted_oldest_first(qpaths: Path) -> None:
    for job_id in (300, 20, 1000):
        make_job(qpaths, job_id)
    assert [p.stem for p in wq.list_jobs()] == ["20", "300", "1000"]


def test_publish_status(qpaths: Path) -> None:
    assert wq.read_status() == 0
    make_job(qpaths, 1)
    make_job(qpaths, 2)
    assert wq.publish_status() == 2
    assert wq.read_status() == 2


def test_worker_processes_in_order_and_cleans_up(qpaths: Path) -> None:
    jobs = [make_job(qpaths, i) for i in (3, 1, 2)]
    seen: list[str] = []
    pending: list[int] = []

    def process(job: dict) -> None:
        seen.append(job["id"])
        pending.append(wq.read_status())

    assert wq.run_worker(process, lambda _j: None) == 3
    assert seen == ["1", "2", "3"]
    assert pending == [3, 2, 1]  # the job being processed still counts
    assert wq.list_jobs() == []
    assert wq.read_status() == 0
    assert not any(Path(j["wav"]).exists() for j in jobs)


def _hold_lock(qdir: str, ready, release) -> None:  # runs in a child process
    wq.QUEUE_DIR = Path(qdir)
    wq.try_acquire_worker_lock()
    ready.set()
    release.wait(5)


def test_worker_exits_when_lock_held(qpaths: Path) -> None:
    make_job(qpaths, 1)
    ctx = multiprocessing.get_context("fork")
    ready, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_hold_lock, args=(str(qpaths), ready, release))
    child.start()
    try:
        assert ready.wait(5)
        assert wq.worker_pid() == child.pid
        assert wq.run_worker(lambda _j: None, lambda _j: None) == 0
        assert len(wq.list_jobs()) == 1
    finally:
        release.set()
        child.join(5)


def test_worker_rechecks_after_release(qpaths: Path, monkeypatch) -> None:
    real_release = wq.release_worker_lock
    calls = {"n": 0}

    def release_then_enqueue() -> None:
        real_release()
        calls["n"] += 1
        if calls["n"] == 1:
            make_job(qpaths, 7)  # a take lands right after the queue looked empty

    monkeypatch.setattr(wq, "release_worker_lock", release_then_enqueue)
    seen: list[str] = []
    wq.run_worker(lambda j: seen.append(j["id"]), lambda _j: None)
    assert seen == ["7"]


def test_give_up_after_max_attempts(qpaths: Path) -> None:
    make_job(qpaths, 1, attempts=wq.MAX_ATTEMPTS)
    processed: list[str] = []
    given_up: list[str] = []
    wq.run_worker(lambda j: processed.append(j["id"]), lambda j: given_up.append(j["id"]))
    assert processed == []
    assert given_up == ["1"]
    assert wq.list_jobs() == []


def test_attempts_persisted_before_processing(qpaths: Path) -> None:
    make_job(qpaths, 1)
    stored: list[int] = []

    def process(job: dict) -> None:
        on_disk = wq.read_job(wq.list_jobs()[0])
        assert on_disk is not None
        stored.append(on_disk["attempts"])

    wq.run_worker(process, lambda _j: None)
    assert stored == [1]


def test_missing_wav_is_dropped(qpaths: Path) -> None:
    job = make_job(qpaths, 1)
    Path(job["wav"]).unlink()
    processed: list[str] = []
    wq.run_worker(lambda j: processed.append(j["id"]), lambda _j: None)
    assert processed == []
    assert wq.list_jobs() == []


def test_worker_survives_exceptions(qpaths: Path) -> None:
    make_job(qpaths, 1)
    make_job(qpaths, 2)
    seen: list[str] = []

    def process(job: dict) -> None:
        seen.append(job["id"])
        if job["id"] == "1":
            raise RuntimeError("boom")

    wq.run_worker(process, lambda _j: None)
    assert seen == ["1", "2"]
    assert wq.list_jobs() == []


def test_malformed_job_is_dropped(qpaths: Path) -> None:
    qpaths.mkdir(parents=True)
    (qpaths / "5.json").write_text("{not json")
    make_job(qpaths, 6)
    seen: list[str] = []
    wq.run_worker(lambda j: seen.append(j["id"]), lambda _j: None)
    assert seen == ["6"]
    assert wq.list_jobs() == []


def test_clear_queue(qpaths: Path) -> None:
    jobs = [make_job(qpaths, i) for i in (1, 2)]
    Path(f"{jobs[0]['wav']}.part").write_bytes(b"")
    wq.clear_queue()
    assert wq.list_jobs() == []
    assert not any(Path(j["wav"]).exists() for j in jobs)
    assert not Path(f"{jobs[0]['wav']}.part").exists()
