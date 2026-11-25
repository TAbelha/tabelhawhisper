# TAbelhaWhisper: noise gate, spinner, transcription queue, saved recordings, deliver to agent

Plan produced by the `planner` subagent (two passes) on 2026-11-24, condensed here.

## Goals

1. Wave bars ignore steady background audio (lo-fi through the laptop speakers).
2. Transcribing spinner rotates in place (no wobble).
3. Record a new take while earlier ones are still transcribing (queue).
4. `save_audio` / `save_audio_dir`: explicit flags, default dir, temp wav cleanup.
5. Deliver to agent: on stop, capture the focused herdr agent pane; when the
   transcription is ready, submit it there (paste + Enter) without stealing focus.
6. Pill timer keeps counting during pause (bug): paused time must not count.

## Progress (2026-11-24)

- [x] Config keys + save-dir resolution (`whisper_core`), `mode` default fixed
- [x] Noise gate + `LevelMeter` in wav writer and streaming
- [x] `write_state` flock + `expect=` CAS
- [x] `bin/whisper_queue.py` + tests
- [x] Pause timer: `paused_at` on pause, `start` shifted on resume, pill freezes while paused
- [x] Orchestrator wiring (stop → enqueue, worker, scoped cancels, save copy)
- [x] Pill: queue badge, "(N)", scoped ✕, in-place spinner
- [ ] Echo cancellation capture (optional, see below; not started)
- [x] Deliver to agent
- [x] Installer, README, CHANGELOG

## Decisions

### Noise gate (display only)
- `whisper_core.NoiseGate`: rolling window (24 chunks ≈ 3 s) of chunk dB; floor
  target = 25th percentile; floor falls instantly, rises ≤ 0.05 dB/chunk after an
  8-chunk warm-up; clamped to [-60, -30] dB; level = clamp((db - floor - 4) / 12).
  (First tuning, margin 8 / range 30 / 10th pct / 0.3 dB, left the bars flat
  when the lo-fi was only ~6-10 dB below the voice; retuned on real recordings.)
- Digital-silence chunks (< -85 dB) are ignored.
- `LevelMeter` keeps the last 60 levels. Used by both `_wav_writer` and
  `whisper_stream` (same scale). `rms_to_level` and `_compute_levels` removed.
- `pcm16_rms` uses stdlib `array`, drops an odd trailing byte.

### What the mic hears (echo cancellation)
- `pw-record` already captures only the default source (the built-in mic); it
  never taps system playback. The lo-fi gets in acoustically: speakers → air →
  mic. Separating voice from that needs signal processing, not a different input.
- The noise gate only fixes the bars. To clean the audio itself (bars and
  transcription), use PipeWire's WebRTC echo canceller
  (`libpipewire-module-echo-cancel`, installed with `libpipewire-0.3-modules`):
  it subtracts what is being played from the mic signal.
- New config `capture_target = ""` → passed as `pw-record --target <node>` when
  set (empty = default source, current behavior). `find_pwrec` must still match.
- install.sh offers (does not force) a drop-in
  `~/.config/pipewire/pipewire.conf.d/60-tabelhawhisper-echo-cancel.conf`
  creating source `tabelhawhisper-aec`; prefer `monitor.mode = true` (reference =
  monitor of the default sink, so apps keep playing to the normal output) if the
  installed PipeWire supports it, else the classic echo-cancel sink. Verify the
  option on this PipeWire version before writing the drop-in.
- The gate stays as a safety net (AEC leaves residue; fans, keyboard).
- Headphones make all of this moot.

### Spinner
- Fixed 18×18 Item with a Canvas 270° arc, `RotationAnimator`, center origin.

### Queue
- `bin/whisper_queue.py`: job files `/tmp/tabelhawhisper-queue/<id>.json`
  (`id` = epoch ms from the wav name), status `/tmp/tabelhawhisper-queue.json`
  `{"pending": n}` (recounted under a flock).
- Single worker (`tabelhawhisper.py work`, procname `twhisper-tx`) guarded by
  `flock` on `worker.lock`; oldest first; re-checks the queue after releasing the
  lock; `attempts` > 2 → give up with an error history entry.
- The worker never writes the recorder state file. `write_state` gains a flock
  plus `expect=` compare-and-set for recorder-vs-recorder races.
- wav is written to `<wav>.part` and renamed when finalized; `stop()` waits for it.
- `stop()`: guard on recording/paused → state transcribing (finalize window) →
  kill (SIGCONT first so stop-from-paused works) → finalize → save copy → enqueue
  → state idle (only if still the same wav) → kick worker.
- `toggle` never cancels anymore. `cancel-recording` (recorder only) and
  `cancel-queue` (clear jobs + kill worker by pid in worker.lock, checked via
  /proc comm). `cancel` alias dispatches by state.
- Pill: badge with pending count while recording; transcribing view whenever the
  queue is non-empty, with "(N)" when N > 1; scoped ✕ buttons.

### Saved recordings
- `save_audio = false`, `save_audio_dir = ""` (→ `~/.local/share/tabelha/tabelhawhisper/recordings`).
  Only `save_audio is True` enables it. `~` expanded; relative → under `$HOME`.
- Copy at stop time, local-time file name `YYYY-MM-DD_HH-MM-SS.wav` (dedup `-1`…).
  History `wav_path` = saved path or null. Temp wav deleted when its job ends.
- Also fixes: `mode` missing from DEFAULTS (config value was ignored).

### Deliver to agent
- `bin/whisper_deliver.py`: pure parsers (proc tree, herdr client argv, pane
  list) + thin wrappers (`capture_target`, `deliver`).
- Target is resolved at stop time (the second Mod+E), 300 ms budget, so switching
  away right after is safe; the pane id is stable even if tabs move:
  1. `niri msg --json focused-window` → must be the terminal (ghostty pid).
  2. herdr client processes descended from that pid (walk `/proc/*/stat` ppid).
     Verified: `herdr session attach work` under fish under ghostty → session
     `work`. Accepted argv forms: `herdr`, `herdr --session S`,
     `herdr session attach S`; the server (`herdr --session S server`) is ignored.
  3. `herdr --session S pane list` → `.result.panes[]`; exactly one has
     `focused: true` per session (verified).
  4. That pane must have `agent` (claude, opencode…); a shell/nvim pane is refused.
- herdr's `focused` is per session and ignores OS focus (it stays true while
  another app is focused), hence step 1.
- Give up (clipboard + "não enviado: motivo") when: focused window is not the
  terminal, several niri windows share the ghostty pid (single-process ghostty
  cannot map window → client; window titles like `camaranave: wiv` are not a
  reliable key), several herdr sessions under it, no focused pane, or not an agent.
  Errors from herdr come as `{"error":{"code":…}}` on stdout with exit 1
  (e.g. `server_not_running`).
- Deliver: `herdr --session S agent prompt <pane_id> <text>` (no `--`, no
  `--wait`), newlines collapsed. Failure → clipboard + "não enviado: <motivo>".
  Success → "Enviado para <label>". History gets `sent_to`. Job stores
  `delivered` after success to avoid double send on retry.
- `send_to_agent = false` config + `--send/--no-send` on toggle/start/stop.
  Precedence: stop-time flag > start-time flag (stored in state) > config.
- install.sh wrapper forwards args; suggested bind `Mod+Shift+E … "--send"`.

## Tests
Config defaults/save-dir resolution; noise gate behavior; write_state CAS;
queue module (ordering, idempotent enqueue, lock, re-check, give-up, missing wav,
exception survival, clear); orchestrator flow (toggle never cancels, stop
enqueues/saves/idle, save failure, newer recording not clobbered, SIGCONT first,
worker drains, scoped cancels); deliver parsers/wrappers; send resolution and
delivery in `_process_job`.

## Manual checklist
1. Lo-fi playing: bars flat when silent, move when speaking (also on a 5 s sentence).
2. Record → stop → record again: badge "1"; first result arrives during the second take.
3. Queue 3 takes: "Transcrevendo... (3)" counts down; history oldest first.
4. ✕ while recording discards only that take; ✕ in transcribing view clears the queue.
5. Pause then stop: transcription arrives. Pause 10 s: timer resumes where it stopped.
6. `save_audio = true`: file appears at stop; false + dir → nothing written.
7. `pkill -9 twhisper-tx` mid-job, then a new take: the killed job is retried.
8. `--send` focused on a Claude pane, switch away: text submitted in that pane.
   Shell pane / browser / second ghostty window → "não enviado: …", clipboard has it.
9. Streaming mode still works; history `wav_path` null.
