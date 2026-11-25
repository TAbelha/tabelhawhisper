from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import whisper_queue


@pytest.fixture
def qpaths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the queue at a temp dir and make sure no lock leaks between tests."""
    qdir = tmp_path / "queue"
    monkeypatch.setattr(whisper_queue, "QUEUE_DIR", qdir)
    monkeypatch.setattr(whisper_queue, "QUEUE_STATUS_PATH", tmp_path / "queue.json")
    yield qdir
    whisper_queue.release_worker_lock()
