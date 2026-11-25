from __future__ import annotations

import struct

from whisper_core import LevelMeter, NoiseGate, pcm16_rms

# Background music picked up by the mic, in dBFS per chunk.
MUSIC = [-48.0, -45.0, -42.0, -46.0, -44.0]


def rms_at(db: float) -> float:
    return 32768.0 * 10 ** (db / 20)


def feed(gate: NoiseGate, dbs: list[float]) -> list[float]:
    return [gate.update(rms_at(db)) for db in dbs]


def test_steady_music_is_silent() -> None:
    gate = NoiseGate()
    levels = feed(gate, MUSIC * 10)
    # A faint flicker on the music's peaks is the price of showing quiet voices.
    assert max(levels[10:]) < 0.2


def test_speech_over_music_is_visible() -> None:
    gate = NoiseGate()
    feed(gate, MUSIC * 6)
    levels = feed(gate, [-22.0] * 4)
    assert min(levels) >= 0.3
    assert gate.floor_db is not None
    assert gate.floor_db <= -44


def test_quiet_voice_close_to_music_is_visible() -> None:
    # Speakers playing loud enough that the voice is only ~8 dB above the
    # music's median (low mic gain): the bars must still follow the voice.
    gate = NoiseGate()
    feed(gate, MUSIC * 6)
    levels = feed(gate, [-37.0] * 4)
    assert min(levels) >= 0.3


def test_continuous_speech_does_not_become_background() -> None:
    gate = NoiseGate()
    feed(gate, MUSIC * 6)
    levels = feed(gate, [-25.0] * 40)
    assert gate.floor_db is not None
    assert gate.floor_db <= -39
    assert levels[-1] > 0.0


def test_floor_falls_immediately() -> None:
    gate = NoiseGate()
    feed(gate, MUSIC * 6)
    feed(gate, [-58.0] * 6)  # under a second
    assert gate.floor_db is not None
    assert gate.floor_db <= -57


def test_quiet_room_keeps_full_range() -> None:
    gate = NoiseGate()
    feed(gate, [-70.0] * 10)
    assert gate.floor_db == NoiseGate.FLOOR_MIN
    level = gate.update(rms_at(-52.0))
    expected = (-52.0 - NoiseGate.FLOOR_MIN - NoiseGate.MARGIN_DB) / NoiseGate.RANGE_DB
    assert abs(level - expected) < 0.01
    assert gate.update(rms_at(-30.0)) == 1.0


def test_digital_silence_is_ignored() -> None:
    gate = NoiseGate()
    feed(gate, MUSIC * 6)
    floor = gate.floor_db
    assert gate.update(0.0) == 0.0
    assert gate.floor_db == floor


def test_floor_is_capped_high() -> None:
    gate = NoiseGate()
    feed(gate, [-10.0] * 30)
    assert gate.floor_db == NoiseGate.FLOOR_MAX


def test_meter_keeps_last_60() -> None:
    meter = LevelMeter()
    levels: list[float] = []
    for _ in range(80):
        levels = meter.push(rms_at(-40.0))
    assert len(levels) == 60


def test_pcm16_rms() -> None:
    assert pcm16_rms(b"") == 0.0
    assert pcm16_rms(b"\x01") == 0.0  # odd trailing byte dropped
    data = struct.pack("<4h", 1000, -1000, 1000, -1000)
    assert abs(pcm16_rms(data) - 1000.0) < 1e-6
