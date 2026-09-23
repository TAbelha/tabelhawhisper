from __future__ import annotations

import numpy as np

from whisper_stream import _compute_levels


def test_compute_levels_silence() -> None:
    chunks = [np.zeros(4096, dtype=np.int16)]
    levels = _compute_levels(chunks)
    assert len(levels) == 1
    assert levels[0] == 0.0


def test_compute_levels_signal() -> None:
    chunk = np.zeros(4096, dtype=np.int16)
    chunk[100:200] = 10000  # some signal
    levels = _compute_levels([chunk])
    assert len(levels) == 1
    assert levels[0] > 0.0


def test_compute_levels_max_60() -> None:
    chunks = [np.ones(4096, dtype=np.int16) * 100 for _ in range(80)]
    levels = _compute_levels(chunks)
    assert len(levels) == 60  # capped at 60
