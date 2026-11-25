"""Shared helpers for tabelhawhisper: config, model, and the on-disk state file.

The state file at ``/tmp/tabelhawhisper.json`` is the single source of truth
shared between the orchestrator (tabelhawhisper), the streaming transcriber
(whisper_stream) and the dms pill widget. It always carries at least
``state`` (``recording`` | ``paused`` | ``transcribing`` | ``done`` | ``idle`` | ``error``)
and, while recording, ``start`` (epoch seconds) so the pill can show elapsed time.

Levels are written to a dedicated file (``/tmp/tabelhawhisper-levels.json``) by the
wav writer thread or the streaming transcriber, avoiding thread-safety issues with
the main state file.

History is persisted in ``~/.config/tabelha/tabelhawhisper/history.json`` as a
ring buffer of completed/errored transcriptions.

Wave bar levels go through a ``NoiseGate`` that tracks the background floor, so
steady sound picked up by the mic (music from the speakers, fans) stays flat and
only louder-than-background input (the user's voice) moves the bars.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
import sys
import tempfile
import tomllib
from array import array
from collections import deque
from datetime import datetime
from pathlib import Path

STATE_PATH = Path("/tmp/tabelhawhisper.json")
LEVELS_PATH = Path("/tmp/tabelhawhisper-levels.json")
HISTORY_DIR = Path.home() / ".config" / "tabelha" / "tabelhawhisper"
HISTORY_PATH = HISTORY_DIR / "history.json"
DEFAULT_RECORDINGS_DIR = (
    Path.home() / ".local" / "share" / "tabelha" / "tabelhawhisper" / "recordings"
)
CONFIG_PATH = Path(
    os.environ.get("TABELHAWHISPER_CONFIG", "~/.config/tabelha/tabelhawhisper/config.toml")
).expanduser()

DEFAULTS = {
    "model": "small",
    "language": "auto",  # auto | pt | en | ... (auto detects pt/en mixed per segment)
    "multilingual": True,  # detect language independently on every segment
    "copy_clipboard": True,
    "history_size": 100,
    "engine": "faster-whisper",
    "device": "cpu",  # cpu | cuda (falls back to cpu if CUDA is unavailable)
    "beam_size": 5,  # higher = more accurate, slower
    "mode": "wav",  # wav | streaming
    "save_audio": False,  # keep a copy of every recording (only `true` enables it)
    "save_audio_dir": "",  # empty -> DEFAULT_RECORDINGS_DIR
    "send_to_agent": False,  # submit the transcript to the herdr agent pane focused at stop
}


def log(msg: str) -> None:
    print(f"[whisper_core] {msg}", file=sys.stderr)


def load_config(path: Path | None = None) -> dict:
    cfg = dict(DEFAULTS)
    p = path or CONFIG_PATH
    if p and p.exists():
        with p.open("rb") as f:
            data = tomllib.load(f)
        cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    return cfg


def read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except FileNotFoundError:
        return {"state": "idle"}
    except json.JSONDecodeError:
        log("read_state: invalid JSON in state file, resetting to idle")
        return {"state": "idle"}


def _atomic_write_json(path: Path, data: object, *, indent: int | None = None) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        Path(tmp_path).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()
        raise


def write_state(patch: dict, *, expect: dict | None = None) -> dict | None:
    """Merge ``patch`` into the existing state (preserving ``start``) and write atomically.

    The read-merge-write runs under an exclusive flock so concurrent writers do not
    lose each other's keys. With ``expect``, the write only happens when every key in
    it still has that value (compare-and-set); otherwise nothing is written and None
    is returned.
    """
    lock_path = STATE_PATH.with_suffix(".lock")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_state()
        if expect and any(state.get(k) != v for k, v in expect.items()):
            return None
        state.update(patch)
        _atomic_write_json(STATE_PATH, state)
    return state


def resolve_save_dir(cfg: dict) -> Path | None:
    """Where to keep recordings, or None when saving is off.

    Only ``save_audio = true`` enables saving; the directory is ignored otherwise.
    An empty directory means the default; ``~`` is expanded and a relative path is
    taken relative to the home directory.
    """
    if cfg.get("save_audio") is not True:
        return None
    raw = str(cfg.get("save_audio_dir") or "").strip()
    if not raw:
        return DEFAULT_RECORDINGS_DIR
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.home() / path
    return path


def saved_recording_path(directory: Path, start_ts: float) -> Path:
    """Local-time file name for a saved recording, deduplicated with -1, -2, ..."""
    stem = datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d_%H-%M-%S")
    candidate = directory / f"{stem}.wav"
    n = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{n}.wav"
        n += 1
    return candidate


SILENCE_DB = -85.0  # below this a chunk is digital silence (muted mic), not room noise


def rms_to_db(rms: float) -> float:
    """RMS amplitude (0-32768) to dBFS."""
    return 20 * math.log10(max(rms, 1.0) / 32768.0)


def pcm16_rms(data: bytes) -> float:
    """RMS of a little-endian signed 16-bit PCM chunk (odd trailing byte dropped)."""
    if len(data) % 2:
        data = data[:-1]
    if not data:
        return 0.0
    samples = array("h")
    samples.frombytes(data)
    if sys.byteorder == "big":
        samples.byteswap()
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class NoiseGate:
    """Map chunk RMS to a 0..1 bar level relative to an adaptive background floor.

    The floor is a low percentile of the last few seconds of chunk loudness. It
    drops immediately when the room gets quieter but rises slowly, so a long
    stretch of continuous speech is not mistaken for background. Steady sound at
    the floor (music, fans) maps to 0; only what rises clearly above it shows.
    """

    # Tuned on recordings with lo-fi playing through the laptop speakers and the
    # mic at ~27%: the voice can sit only 6-10 dB above the music, so the margin
    # is small and the range short. Music peaks may flicker slightly.
    WINDOW = 24  # chunks (~3 s at 128 ms per chunk)
    PERCENTILE = 0.25
    WARMUP = 8  # chunks during which the floor follows the target freely
    RISE_DB_PER_CHUNK = 0.05  # slow, so long speech does not lift the floor
    MARGIN_DB = 4.0
    RANGE_DB = 12.0
    FLOOR_MIN = -60.0
    FLOOR_MAX = -30.0

    def __init__(self) -> None:
        self._window: deque[float] = deque(maxlen=self.WINDOW)
        self._floor: float | None = None
        self._seen = 0

    @property
    def floor_db(self) -> float | None:
        return self._floor

    def update(self, rms: float) -> float:
        db = rms_to_db(rms)
        if db < SILENCE_DB:
            return 0.0
        self._window.append(db)
        self._seen += 1
        ordered = sorted(self._window)
        target = ordered[int(self.PERCENTILE * (len(ordered) - 1))]
        if self._floor is None or target < self._floor or self._seen <= self.WARMUP:
            floor = target
        else:
            floor = min(target, self._floor + self.RISE_DB_PER_CHUNK)
        self._floor = _clamp(floor, self.FLOOR_MIN, self.FLOOR_MAX)
        return _clamp((db - self._floor - self.MARGIN_DB) / self.RANGE_DB, 0.0, 1.0)


class LevelMeter:
    """Gated levels for the most recent ``max_samples`` chunks of one recording."""

    def __init__(self, max_samples: int = 60) -> None:
        self._gate = NoiseGate()
        self._levels: deque[float] = deque(maxlen=max_samples)

    def push(self, rms: float) -> list[float]:
        self._levels.append(round(self._gate.update(rms), 3))
        return list(self._levels)


def write_levels(levels: list[float]) -> None:
    """Write audio levels to the dedicated levels file (thread-safe, atomic)."""
    _atomic_write_json(LEVELS_PATH, {"levels": levels})


def read_history() -> dict:
    try:
        return json.loads(HISTORY_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"entries": []}


def write_history(entry: dict, history_size: int = 100) -> None:
    """Append an entry to the history ring buffer (atomic write)."""
    hist_dir = HISTORY_PATH.parent
    hist_dir.mkdir(parents=True, exist_ok=True)
    history = read_history()
    history["entries"].append(entry)
    history["entries"] = history["entries"][-history_size:]
    _atomic_write_json(HISTORY_PATH, history, indent=2)


_MODEL = None


def get_model(model_size: str, language: str | None = None, device: str = "cpu"):
    import faster_whisper

    global _MODEL
    if _MODEL is None:
        try:
            _MODEL = faster_whisper.WhisperModel(model_size, device=device)
        except Exception:
            if device != "cpu":
                _MODEL = faster_whisper.WhisperModel(model_size, device="cpu")
            else:
                raise
    return _MODEL


def transcribe_options(cfg: dict) -> tuple[str | None, bool]:
    """Resolve the kwargs for ``model.transcribe`` from config.

    ``language="auto"`` (or empty/``None``) becomes ``None`` so faster-whisper
    auto-detects; ``multilingual`` enables per-segment language detection so pt
    and en can be mixed within a single recording.
    """
    raw = cfg.get("language") or "auto"
    lang = None if raw in ("auto", "", None) else raw
    multilingual = bool(cfg.get("multilingual", True))
    return lang, multilingual


def transcribe_file(
    path: str,
    model_size: str,
    language: str | None,
    device: str = "cpu",
    multilingual: bool = True,
    beam_size: int = 5,
) -> str:
    model = get_model(model_size, language, device)
    lang, ml = transcribe_options({"language": language, "multilingual": multilingual})
    segments, _ = model.transcribe(
        path,
        language=lang,
        multilingual=ml,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters={
            "threshold": 0.3,
            "min_speech_duration_ms": 150,
            "speech_pad_ms": 300,
        },
        condition_on_previous_text=False,
        temperature=[0.0, 0.4, 0.6, 0.8],
    )
    return "".join(seg.text for seg in segments).strip()
