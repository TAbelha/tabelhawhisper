# Plano de conclusão v1.1.0

## Estado atual (2026-09-12)

### Aplicado e confirmado (git diff)
- `install.sh`: CFG_DIR corrigido para `~/.config/tabelha/whisper-dictate` + migração automática do config antigo (`tabela/` → `tabelha/`)
- `config/whisper-dictate.toml.example`: cabeçalho corrigido para `tabelha`
- `pyproject.toml`: versão `1.1.0`
- `uv.lock`: regenerado (name `tabelhawhisper`, version `1.1.0`)
- `CHANGELOG.md`: reordenado (1.0.0/1.0.1/1.1.0) + seção 1.1.0 com todas as entradas
- `bin/whisper_dictate.py` (parcial):
  - docstring atualizada (mention pill + cancel)
  - `find_pwrec()`: check `/tmp/whisper-dictate` (suporta wav por sessão)
  - `start()`: wav por sessão (`/tmp/whisper-dictate-<ts>.wav`), grava `wav`/`python`/`script`/`indicator` no state
  - `stop()`: spawna `transcribe <wav>` como filho destacado (não transcreve inline)
  - `toggle()`: gravando→stop, transcrevendo→cancel+start, ocioso→start
  - `main()`: subcomandos `cancel` e `transcribe` registrados

### Faltando (edições travadas não aplicaram)
1. **`bin/whisper_core.py:23`** → `"model": "small"` precisa virar `"medium"`
2. **`bin/whisper_dictate.py`** → faltam `_kill_force()`, `transcribe()` e `cancel()` (arquivo quebrado, NameError)
3. **`config/whisper-dictate.toml.example:4`** → `model = "small"` precisa virar `"medium"` + comentário do `indicator` (linha 10) ainda diz "standalone quickshell app"
4. **Fase B**: QML DictatePill (não iniciada)
5. **Fase C**: testes + README (não iniciada)
6. **Fase D**: CI + commit + push + tag + rename + delete (não iniciada)

---

## Fase A: concluir Python (edições que travaram)

### Estratégia: reescrever o arquivo inteiro via Write (não edits incrementais)

Reescrever `bin/whisper_dictate.py` completo com todas as funções. Depois de escrever:
- `uv run ruff check bin/`
- `uv run basedpyright bin/`

Adicionar ao arquivo as 3 funções que faltam:

```python
def _kill_force(pids: list[int]) -> None:
    """SIGINT then SIGTERM then SIGKILL: used by cancel for stuck CTranslate2."""
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGINT)
    time.sleep(0.3)
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
    time.sleep(0.3)
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def transcribe(wav_path: str) -> None:
    """Transcribe a wav file and write the result to the state file.

    Runs as a detached child process so the dms pill can cancel it.
    """
    _set_procname("twhisper-tx")
    cfg = load_config()
    write_state({"state": "transcribing"})
    log(f"transcribe start wav={wav_path}")
    try:
        text = transcribe_file(
            wav_path,
            cfg["model"],
            cfg["language"],
            cfg.get("device", "cpu"),
            cfg.get("multilingual", True),
            cfg.get("beam_size", 5),
        )
    except Exception as e:
        log(f"transcribe error: {e}")
        write_state({"state": "done", "text": f"[error: {e}]"})
        return

    write_state({"state": "done", "text": text})
    if text.strip():
        if cfg.get("copy_clipboard"):
            subprocess.run(["wl-copy"], input=text.encode(), check=False)
        _notify(text)
    log(f"transcribe done textlen={len(text)}")


def cancel(cfg: dict) -> None:
    """Kill any running transcription/recording and reset to idle."""
    state = read_state()
    cur_state = state.get("state", "idle")
    if cur_state == "idle":
        log("cancel: already idle, nothing to do")
        return

    pids = sorted(set(find_pwrec()) | set(_read_pids()))
    log(f"cancel killing pids={pids} state={cur_state}")
    _kill_force(pids)
    PID_FILE.unlink(missing_ok=True)

    wav = state.get("wav", cfg.get("wav", "/tmp/whisper-dictate.wav"))
    with contextlib.suppress(OSError):
        Path(wav).unlink(missing_ok=True)

    write_state({"state": "idle", "text": ""})
    log("cancel done")
```

Inserir entre `watch()` (linha ~239) e `toggle()` (linha ~242).

### Edits pontuais restantes
- `bin/whisper_core.py:23` → `"model": "medium"`
- `config/whisper-dictate.toml.example:4` → `model = "medium"`
- `config/whisper-dictate.toml.example:10` → `indicator = true          # show the floating pill while recording/transcribing`

---

## Fase B: QML DictatePill

Espelhar o `recPill` do `screenCaptureToolbar/CaptureToolbar.qml:2994`. O novo Widget.qml terá:
- `import Quickshell.Wayland` (pra `WlrLayershell`, `ExclusionMode`)
- Componente inline `DictatePill: PanelWindow` com:
  - `visible: (root.recording || root.transcribing) && root.indicator`
  - `WlrLayershell.layer: WlrLayer.Overlay`, `exclusionMode: ExclusionMode.Ignore`
  - Posição: top-right via `anchors + margins`
  - **Gravando**: dot vermelho pulsante + timer + botões Stop e X
  - **Transcrevendo**: "Transcrevendo…" + spinner + botão X
  - Botões via `Quickshell.execDetached([python, script, "stop"|"cancel"])`
  - `python`/`script` lidos do stateObj
- `plugin.json`: manter como está (já tem `dankbar-widget`)

---

## Fase C: config, docs, testes

- `tests/test_config.py:10` → assert `small` → `medium`
- Novo `tests/test_cancel.py` → testa `cancel` no-op idle, transições de estado
- `README.md` / `README.pt-BR.md`:
  - Tabela de config: default `small` → `medium`
  - "No floating windows, no always-on indicators" → pill só-enquanto-ativo
  - Documentar cancel + botões + comportamento Mod+E durante transcrição
- `CHANGELOG.md` → já atualizado (seção 1.1.0)

---

## Fase D: CI + git

1. Rodar CI local:
   ```
   uv run ruff format --check .
   uv run ruff check .
   uv run basedpyright bin
   uv run typos
   uv run vulture bin tests --min-confidence 80
   uv run pytest --cov --cov-report=term-missing
   ```
2. `git add -A && git commit -m "feat: floating pill, cancellable transcription, default medium"`
3. `git push origin main`
4. `git tag v1.1.0 && git push origin v1.1.0` (release auto via workflow)
5. `gh repo rename TAbelhaDev/tabelawhisper tabelhawhisper` (se permissão ok)
6. `git branch -d chore/rename-whisper && git push origin --delete chore/rename-whisper`

---

## Notas

- O `whisper_dictate.py` reescrito deve ter ~330 linhas (287 atuais + ~40 das 3 funções faltantes)
- O `Widget.qml` reescrito deve ter ~250 linhas (112 atuais + ~140 do DictatePill)
- Config `indicator` agora é respeitado: python grava no state, pill lê
- State file ganha campos `wav`, `python`, `script`, `indicator` (backwards compat: defaults se ausentes)
