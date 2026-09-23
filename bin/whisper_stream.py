#!/usr/bin/env python3
"""Streaming transcriber for tabelhawhisper (v2.0).

Reads raw PCM16 mono 16 kHz from stdin, keeps a rolling buffer,
re-transcribes periodically, and writes audio levels to the dedicated
levels file for the QML pill to render as wave bars.
"""

from __future__ import annotations

import contextlib
import sys
import time

import numpy as np

from whisper_core import get_model, load_config, transcribe_options, write_levels, write_state

RETRANSCRIBE_EVERY = 2.0


def _compute_levels(chunks: list[np.ndarray]) -> list[float]:
    """Compute RMS levels from PCM chunks, normalized to 0..1."""
    levels = []
    for chunk in chunks:
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
        levels.append(min(1.0, rms / 32768.0))
    return levels[-60:]


def main() -> None:
    cfg = load_config()
    model = get_model(cfg["model"], cfg["language"], cfg.get("device", "cpu"))
    lang, multilingual = transcribe_options(cfg)
    beam_size = cfg.get("beam_size", 5)
    vad_parameters = {"threshold": 0.3, "min_speech_duration_ms": 150, "speech_pad_ms": 300}
    temperature = [0.0, 0.4, 0.6, 0.8]

    buf: list[np.ndarray] = []
    last = time.time()
    while True:
        data = sys.stdin.buffer.read(4096)
        if not data:
            break
        chunk = np.frombuffer(data, dtype=np.int16)
        buf.append(chunk)

        # Write levels periodically
        if len(buf) % 8 == 0:
            with contextlib.suppress(Exception):
                write_levels(_compute_levels(buf[-20:]))

        if time.time() - last >= RETRANSCRIBE_EVERY and buf:
            audio = np.concatenate(buf).astype(np.float32) / 32768.0
            segments, _ = model.transcribe(
                audio,
                language=lang,
                multilingual=multilingual,
                beam_size=beam_size,
                vad_filter=True,
                vad_parameters=vad_parameters,
                condition_on_previous_text=False,
                temperature=temperature,
            )
            text = "".join(s.text for s in segments).strip()
            write_state({"state": "recording", "text": text})
            last = time.time()

    # Final transcription
    if buf:
        audio = np.concatenate(buf).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(
            audio,
            language=lang,
            multilingual=multilingual,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters=vad_parameters,
            condition_on_previous_text=False,
            temperature=temperature,
        )
        text = "".join(s.text for s in segments).strip()
        write_state({"state": "done", "text": text})

    # Clear levels on completion
    from whisper_core import LEVELS_PATH

    with contextlib.suppress(Exception):
        LEVELS_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
