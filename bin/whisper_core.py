"""Shared helpers for tabelhawhisper: config, model, and the on-disk state file.

The state file at ``/tmp/whisper-dictate.json`` is the single source of truth
shared between the orchestrator (whisper_dictate), the streaming transcriber
(whisper_stream) and the dms pill widget. It always carries at least
``state`` (``recording`` | ``paused`` | ``transcribing`` | ``done`` | ``idle`` | ``error``)
and, while recording, ``start`` (epoch seconds) so the pill can show elapsed time.

Levels are written to a dedicated file (``/tmp/whisper-dictate-levels.json``) by the
wav writer thread or the streaming transcriber, avoiding thread-safety issues with
the main state file.

History is persisted in ``~/.config/tabelha/whisper-dictate/history.json`` as a
ring buffer of completed/errored transcriptions.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import sys
import tempfile
import tomllib
from pathlib import Path

STATE_PATH = Path("/tmp/whisper-dictate.json")
LEVELS_PATH = Path("/tmp/whisper-dictate-levels.json")
HISTORY_DIR = Path.home() / ".config" / "tabelha" / "whisper-dictate"
HISTORY_PATH = HISTORY_DIR / "history.json"
CONFIG_PATH = Path(
    os.environ.get("WHISPER_DICTATE_CONFIG", "~/.config/tabelha/whisper-dictate/config.toml")
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


def write_state(patch: dict) -> dict:
    """Merge ``patch`` into the existing state (preserving ``start``) and write atomically."""
    state = read_state()
    state.update(patch)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=str(STATE_PATH.parent))
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(state, f, ensure_ascii=False)
        Path(tmp_path).replace(STATE_PATH)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()
        raise
    return state


def rms_to_level(rms: float) -> float:
    """Convert RMS amplitude (0–32768) to a 0.0–1.0 level via dB mapping."""
    db = 20 * math.log10(max(rms, 1.0) / 32768.0)
    return max(0.0, min(1.0, (db + 60.0) / 60.0))


def write_levels(levels: list[float]) -> None:
    """Write audio levels to the dedicated levels file (thread-safe, atomic)."""
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=str(LEVELS_PATH.parent))
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump({"levels": levels}, f)
        Path(tmp_path).replace(LEVELS_PATH)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()
        raise


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
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=str(hist_dir))
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        Path(tmp_path).replace(HISTORY_PATH)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()
        raise


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
