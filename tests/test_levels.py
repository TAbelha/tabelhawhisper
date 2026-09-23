from __future__ import annotations

from whisper_core import rms_to_level


def test_silence() -> None:
    assert rms_to_level(0.0) == 0.0


def test_quiet_speech() -> None:
    # ~-40 dBFS → level ~0.33
    level = rms_to_level(327.0)  # 327/32768 ≈ -40 dBFS
    assert 0.2 < level < 0.5


def test_normal_speech() -> None:
    # ~-20 dBFS → level ~0.67
    level = rms_to_level(3276.0)
    assert 0.5 < level < 0.85


def test_loud_signal() -> None:
    # ~-6 dBFS → level ~0.9
    level = rms_to_level(23000.0)
    assert 0.8 < level <= 1.0


def test_full_scale() -> None:
    assert rms_to_level(32768.0) == 1.0


def test_very_small_signal() -> None:
    # -60 dBFS or below → 0.0
    assert rms_to_level(3.0) == 0.0
