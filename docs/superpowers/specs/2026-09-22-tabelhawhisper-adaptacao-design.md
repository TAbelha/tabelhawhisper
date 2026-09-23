# Spec: tabelhawhisper v2.0 — pill flutuante + histórico + org TAbelha

## Contexto

tabelhawhisper é um plugin DMS (DankMaterialShell) para ditado por voz local:
grava áudio via PipeWire (pw-record), transcreve com faster-whisper, copia
pro clipboard e mostra notificação. Estado compartilhado via JSON em `/tmp/`,
reprodutor Python或QML faz polling a cada 250ms.

Versão atual (v1.1.0): widget de barra com mic+timer durante gravação,
sem controles de pausa, sem histórico, sem ondas de som. Três live modes
(off/partial/streaming) configuráveis via config.toml. Deixa o user com
estados inobserváveis durante transcrição (sem feedback visual durante a
chamada longa de transcribe).

**Problema:** sem controles durante gravação (pausa/cancelar/concluir),
sem ondas de som, sem histórico acessível, sem integração com clipboard
do Dunk. Interface primitiva demais pra uso real.

**Objetivo:** adaptar o plugin pra experiência em par com o Screen Capture
Toolbar do Dunke (pill flutuante, controles, ondas, histórico), pronto
pra publicar no registro DMS e morar na nova org TAbelha.

## Decisões confirmadas (não reabrir)

1. **Dois modos, não três:** wav + streaming. Partial removido (redundante
   com streaming). `live_mode` da config removido.
2. **Pausa:** só no modo wav. Streaming sem pausa (botão oculto).
3. **Ondas de som reais:** PCM lido do mic via pipe, níveis RMS calculados
   pelo Python, renderizados como barras no QML. Sem ícone animado.
4. **Histórico:** persistente em `~/.config/tabelha/whisper-dictate/history.json`,
   anel de 100 entradas (configurável), erros incluídos.
5. **Clipboard:** serviço interno DMS (`clipboard.store`) + auto-copy
   mantido ao concluir.
6. **Pill flutuante:** arrastável, posição persistida (padrão recPill do
   Screen Capture Toolbar). Show/hide via state.
7. **Plugin type:** composite (daemon pill + widget bar).
8. **Org:** repo novo em `github.com/TAbelha/tabelhawhisper` (privado),
   push fresco. Dir local: `~/codigo/tabelha/tabelhawhisper`.
9. **Version bump:** 2.0.0 (mudança de UI/comportamento).
10. **Gravação via pipe:** Python lê PCM do pw-record (stdout pipe),
    escreve wav incremental, calcula níveis. Pausa = SIGSTOP/SIGCONT
    no pw-record. Padrão coerente para dois modos.

## Arquitetura

### Plugin manifest (type: composite)

```json
{
  "id": "whisperDictate",
  "name": "TAbelha Whisper",
  "description": "Ditado por voz local: grava, transcreve com faster-whisper, pilha flutuante com controles e histórico de transcrições na barra.",
  "category": "utilities",
  "version": "2.0.0",
  "author": "Ian Soares",
  "icon": "mic",
  "type": "composite",
  "components": {
    "daemon": "./DictatePill.qml",
    "widget": "./HistoryWidget.qml"
  },
  "capabilities": ["dankbar-widget", "ipc"],
  "permissions": ["process"],
  "requires_dms": ">=1.2.0",
  "dependencies": [
    "faster-whisper",
    "pipewire",
    "pw-record",
    "notify-send",
    "wl-clipboard"
  ],
  "repo": "https://github.com/TAbelha/tabelhawhisper",
  "compositors": ["any"],
  "distro": ["any"],
  "startupCheck": "./StartupCheck.qml"
}
```

**StartupCheck.qml:** QML não-visual (QtObject) que expõe `check(done)`.
Verifica: binário `pw-record` no PATH, python3 disponível, venv/whisper
instalado (testa import faster_whisper). `done(null)` se ok, `done({title, details})`
se falha.

### Canal de IPC: state file (com polling)

Mantém o padrão existente. Extensões:

```json
{
  "state": "recording | paused | transcribing | done | idle | error",
  "start": 1712345678,
  "text": "",
  "mode": "wav | streaming",
  "wav": "/tmp/whisper-dictate-<ts>.wav",
  "levels": [0.1, 0.4, 0.2, 0.05, 0.3, ...],
  "python": "/home/user/codigo/tabelha/tabelhawhisper/.venv/bin/python",
  "script": "/home/user/codigo/tabelha/tabelhawhisper/bin/whisper_dictate.py",
  "indicator": true
}
```

**Estados novos:** `paused` (distinto de recording; pill mostra dot
amarelo + botão continuar). `levels`: array de ~60 floats normalizados
(0..1), últimas ~2s de áudio a 16kHz com chunk 4096 → atualização a
cada ~125ms. Escrita pelo Python a cada N chunks (~100ms). Só durante
gravando/pausado (silenciado em transcribing/done/idle).

**Thread safety:** `_wav_writer` roda em thread daemon e só escreve
`levels` via arquivo dedicado `/tmp/whisper-dictate-levels.json` (não
tocá no state file principal). QML lê dois arquivos: state + levels.
Thread principal (CLI handlers) é a única que escreve no state file.
Zero conflito de concorrência.

### Config (mudanças)

Removidos: `live_mode`, `partial_interval`, `indicator`
Adicionados: `history_size` (default 100)
Mantidos: model, language, multilingual, copy_clipboard, beam_size, device, engine

Posição da pill (pill_screen, pill_x, pill_y) vive em `pluginData`,
não em config.toml (como o Screen Capture Toolbar faz com `recPill*`).

### Histórico (persistente)

Arquivo: `~/.config/tabelha/whisper-dictate/history.json`

```json
{
  "entries": [
    {
      "ts": 1712345678,
      "mode": "wav",
      "state": "done",
      "text": "transcrição completa...",
      "wav_path": "/tmp/whisper-dictate-1712345678.wav"
    },
    {
      "ts": 1712345600,
      "mode": "streaming",
      "state": "error",
      "text": "[error: audio format unsupported]",
      "wav_path": null
    }
  ]
}
```

Escrita atômica: JSON → `/tmp/whisper-dictate-history-tmp.json` → rename.
Leitura: widget lê direto (via FileView ou JS `File` read). Anel:
quando `entries.length > history_size`, remove do início.

## Seção 1: Backend Python

### Arquivos alterados

- `bin/whisper_dictate.py` — reescrito quase por completo
- `bin/whisper_stream.py` — adiciona cálculo de levels
- `bin/whisper_core.py` — histórico, write_state atômico, `read_state`
  tolera JSON inválido com warning (não default silencioso)

### whisper_dictate.py — mudanças

#### Novo `start()`

```python
def start(cfg: dict) -> None:
    ts = int(time.time())
    wav = f"/tmp/whisper-dictate-{ts}.wav"
    mode = cfg["mode"]  # "wav" ou "streaming" (único campo)
    write_state({"state": "recording", "start": ts, "text": "",
                 "mode": mode, "wav": wav, "python": sys.executable,
                 "script": str(SCRIPT_DIR / "whisper_dictate.py")})

    if mode == "wav":
        # Pipe do pw-record pra stdout, Python lê e escreve wav
        pw = subprocess.Popen(
            ["pw-record", "--format", "s16", "--rate", "16000",
             "--channels", "1", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True)
        pids = [pw.pid]
        # Writer thread lê stdout, calcula levels, append wav
        t = threading.Thread(target=_wav_writer, args=(pw.stdout, wav, ts),
                             daemon=True)
        t.start()
    elif mode == "streaming":
        pw = subprocess.Popen(
            ["pw-record", "--format", "s16", "--rate", "16000",
             "--channels", "1", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True)
        st = subprocess.Popen(
            [sys.executable, str(SCRIPT_DIR / "whisper_stream.py")],
            stdin=pw.stdout, ...)
        pids = [pw.pid, st.pid]

    PID_FILE.write_text(json.dumps({"pids": pids, "mode": mode}))
    time.sleep(0.5)
    # Verificação pós-start (padrão atual)
```

#### Novo `_wav_writer()` (thread daemon, wav mode)

```python
def _wav_writer(stdout_pipe, wav_path, start_ts):
    """Lê PCM do pw-record, escreve wav + calcula levels."""
    import wave, struct
    sample_rate = 16000
    channels = 1
    sample_width = 2  # s16le

    with wave.open(wav_path, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)

        chunk_size = 4096  # bytes
        levels: list[float] = []
        max_level_samples = 60  # últimas ~2s a 16kHz/4096*2

        while True:
            data = stdout_pipe.read(chunk_size)
            if not data:
                break

            wf.writeframes(data)

            # RMS do chunk
            samples = struct.unpack(f'<{len(data)//2}h', data)
            rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
            level = min(1.0, rms / 32768.0)
            levels.append(level)
            levels = levels[-max_level_samples:]

            # Atualizar levels (arquivo dedicado, não state file)
            _update_levels(levels)  # escreve em /tmp/whisper-dictate-levels.json
```

#### Novos subcomandos CLI: `pause`, `resume`

```python
def pause(cfg: dict) -> None:
    """SIGSTOP no pw-record, state → paused."""
    state = read_state()
    if state.get("state") != "recording" or state.get("mode") != "wav":
        return
    pids = _read_pids()
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGSTOP)
    write_state({"state": "paused"})


def resume(cfg: dict) -> None:
    """SIGCONT no pw-record, state → recording."""
    state = read_state()
    if state.get("state") != "paused":
        return
    pids = _read_pids()
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGCONT)
    write_state({"state": "recording"})
```

#### `cancel()` — mantém padrão atual (já implementado)

#### `stop()` — adaptado pra modo wav (novo padrão)

```python
def stop(cfg: dict) -> None:
    state = read_state()
    mode = state.get("mode", "wav")
    wav = state.get("wav", cfg.get("wav"))
    pids = sorted(set(find_pwrec()) | set(_read_pids()))
    _kill(pids)
    PID_FILE.unlink(missing_ok=True)

    if mode == "wav":
        write_state({"state": "transcribing"})
        tx_pid = _spawn([sys.executable, str(SCRIPT_DIR / "whisper_dictate.py"),
                         "transcribe", wav])
        PID_FILE.write_text(json.dumps({"pids": [tx_pid], "mode": mode}))
    elif mode == "streaming":
        final = read_state()
        text = final.get("text", "")
        _finish(text, cfg)
```

#### `_finish()` — extraído (era inline em stop e transcribe)

```python
def _finish(text: str, cfg: dict) -> None:
    """Grava resultado no histórico + clipboard + notificação."""
    write_state({"state": "done", "text": text})
    _write_history(state=read_state(), text=text)
    if text.strip():
        if cfg.get("copy_clipboard"):
            _clipboard_store(text)  # novo: usa DMSService em vez de wl-copy
        _notify(text)
```

#### `_clipboard_store()` — novo (DMS integration)

```python
def _clipboard_store(text: str) -> None:
    """Envia texto pro clipboard via wl-copy E informa o DMS clipboard store.
    Dual: wl-copy seta o Wayland clipboard direto; DMS clipboard store
    adiciona ao histórico do Dunk."""
    subprocess.run(["wl-copy"], input=text.encode(), check=False)
    # Informar DMS via IPC (se disponível)
    subprocess.run(
        ["dms", "ipc", "call", "clipboardService", "store",
         json.dumps({"data": text, "mimeType": "text/plain;charset=utf-8"})],
        check=False, capture_output=True)
```

#### `_write_history()` — novo

```python
import tempfile, os
HISTORY_DIR = Path.home() / ".config" / "tabelha" / "whisper-dictate"
HISTORY_PATH = HISTORY_DIR / "history.json"

def _write_history(state: dict, text: str, cfg: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history = _read_history()
    entry = {"ts": int(time.time()), "mode": state.get("mode"),
             "state": state.get("state"), "text": text,
             "wav_path": state.get("wav")}
    history["entries"].append(entry)
    history_size = cfg.get("history_size", 100)
    history["entries"] = history["entries"][-history_size:]
    # Escrita atômica
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(HISTORY_DIR))
    try:
        with os.fdopen(tmp_fd, 'w') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(HISTORY_PATH))
    except:
        os.unlink(tmp_path)
        raise
```

### whisper_stream.py — adiciona levels

Na chamada de transcrição (buffer rolante + final), após concatenar audio
e transcrever, calcular RMS dos últimos chunks e escrever no state:

```python
levels = _compute_levels(buf[-20:])  # últimos 20 chunks
write_state({"state": "recording", "text": text, "levels": levels})
```

### whisper_core.py — mudanças

- `write_state()`: **escrita atômica** (tmp + rename). Corrige risco
  de corrupção apontado na review OCR.
- `read_state()`: em caso de JSONDecodeError, loga warning + retorna
  default idle (não silencia).
- `get_model()`: mantém padrão (singleton + fallback CPU).
- Novo: `_read_history()`, `_write_history()` movidos pra core
  (podem ser chamados por whisper_dictate e por whisper_stream).

## Seção 2: Pill flutuante QML (DictatePill.qml)

### Tipo de componente

`PluginComponent` (composite daemon). Extensão do plugin `screenCaptureToolbar`.

### PanelWindow overlay

```qml
PanelWindow {
    id: dictatePill
    visible: root.pillVisible

    WlrLayershell.layer: WlrLayershell.Overlay
    WlrLayershell.exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    anchors { top: true; left: true; right: true; bottom: true }

    // Dimensão: compacta 260px, expandida 440px (por padrão recPill)
    width: dictatePillBg.width + 12
    height: 60
}
```

### Posição

`recPillLocalX/screen`, `recPillLocalY/screen` (funções auxiliares
copiadas do screenCaptureToolbar), lendo `pluginData.pillScreenName`,
`pluginData.pillX`, `pluginData.pillY`. Persistência:
`pluginService.savePluginData("whisperDictate", "pillX", x)`.

### Drag (botão direito)

Mesmo padrão do recPill: `beginRecPillDrag()`, `endRecPillDrag()`,
snap em bordas, `updateRecPillDrag()` com mouse position global
(`screen.x + localMouseX`).

### Estados QML

```qml
property bool isRecording: false
property bool isPaused: false
property bool isTranscribing: false
property var levels: []
property int elapsed: 0
```

Leitura: dois `FileView` (poll 250ms): state (`/tmp/whisper-dictate.json`)
+ levels (`/tmp/whisper-dictate-levels.json`). Separados por thread safety
(writer thread só escreve levels).
Binding:
```qml
onStateObjChanged: {
    const st = stateObj.state || "idle"
    root.isRecording = st === "recording"
    root.isPaused = st === "paused"
    root.isTranscribing = st === "transcribing"
    root.startTime = stateObj.start || 0
    root.pillVisible = root.isRecording || root.isPaused || root.isTranscribing
}
onLevelsObjChanged: {
    root.levels = levelsObj.levels || []
}
```

### Renderização por estado

**Collapsed (default):**

```qml
Item {
    visible: !dictatePill.isTranscribing
    RowLayout {
        // Dot vermelho pulsante (gravando) / amarelo fixo (pausado)
        // Timer mm:ss (JetBrains Mono, largura fixa 70px)
        // Barras de onda (Row de Rectangles, altura = level * maxBarHeight)
        // Botão stop (squircle, padrão Screen Capture Toolbar)
    }
}
```

**Ondas (barras):**

```qml
Row {
    spacing: 2
    Repeater {
        model: Math.min(root.levels.length, 16)
        Rectangle {
            width: 3; height: 2
            color: Theme.primary
            property real barLevel: root.levels[root.levels.length - 1 - index] || 0
            implicitHeight: barLevel * 30  // max 30px
            Behavior on height { NumberAnimation { duration: 80 } }
        }
    }
}
```

**Transcrevendo:**

```qml
Item {
    visible: root.isTranscribing
    RowLayout {
        // Spinner (rotation animation) + "Transcrevendo..." (StyledText)
        // Botão X (cancelar)
    }
}
```

**Botões de controle (expanded):**

| state | Botões visíveis |
|---|---|
| recording | ⏸ pausa · ⏹ concluir · ✕ cancelar |
| paused | ▶ continuar · ⏹ concluir · ✕ cancelar |
| transcribing | ✕ cancelar |

Ações via `Quickshell.execDetached([python, script, "pause"|"resume"|"stop"|"cancel"])`.
`python`/`script` lidos do stateObj.

### Timer elapsed

```qml
Timer {
    interval: 1000
    running: root.isRecording || root.isPaused
    repeat: true
    onTriggered: root.elapsed = Math.max(0, Math.floor(Date.now()/1000 - root.startTime))
}
```

Congelado em `paused` (elapsed não muda; timer continua pra manter
o valor mas `Date.now()/1000 - start` já reflete o tempo real;
se quiser congelar visualmente, usar `elapsedSinceStart` contando
só tempo em recording — aceitar simplificação: elapsed = Date.now-start).

### IpcHandler

```qml
IpcHandler { target: "whisperDictate"
    function ping(): string { return "pong" }
    function status(): string { return JSON.stringify(stateObj) }
    function hide(): string { root.pillVisible = false; return "hidden" }
    function show(): string { root.pillVisible = true; return "shown" }
}
```

## Seção 3: Widget da barra + histórico (HistoryWidget.qml)

### Tipo de componente

`PluginComponent` (composite widget), `BasePill`.

### Ícone na barra

```qml
BasePill {
    id: root
    content: Component {
        Item {
            DankIcon {
                name: "history"
                size: Theme.barIconSize(...)
                color: Theme.widgetIconColor
            }
        }
    }
}
```

Click esquerdo → abre `historyPopout`. Click direito → context menu
(limpar histórico).

### History popout

`PanelWindow` overlay (padrão ClipboardButton com `contextMenuWindow`).
Ancorado ao ícone na barra (mesma lógica de `openContextMenu()` do
ClipboardButton). `WlrLayershell.layer: Overlay`.

```qml
PanelWindow {
    id: historyPopout
    visible: false

    // Leitura do histórico: FileView em history.json
    FileView {
        id: historyFile
        path: "/home/user/.config/tabelha/whisper-dictate/history.json"
        onLoaded: root.history = JSON.parse(text()).entries || []
    }

    // Reload ao abrir
    function open() {
        historyFile.reload()
        visible = true
    }
}
```

### Conteúdo do popout

```qml
Column {
    // Header: "TAbelha Whisper" + botão limpar (delete_sweep)
    // Lista de itens (Repeater sobre history entries, newest first):
    //   Item -> Row { timestamp_preview, text_preview (2 linhas), badge_erro? }
    //   Click no item → expande inline (Item.expanded = !expanded)
    //     → texto completo (ScrollView) + botão "Copiar"
    // Estado vazio: StyledText "Nenhuma transcrição ainda"
}
```

### Copiar

```qml
MouseArea {
    onClicked: {
        DMSService.sendRequest("clipboard.store", {
            data: item.text,
            mimeType: "text/plain;charset=utf-8"
        }, response => {
            if (!response.error) ToastService.showToast("Copiado!")
        })
    }
}
```

### Erros

Item com state `error`: texto vermelho, sem botão copiar. Clique
ainda expande (pode ser útil pra debug/ver o erro completo).

### Limpar

Botão no rodapé → confirmação simples (overlay ou `Dialog` do tema)
→ deleta `history.json` (ou esvazia `{"entries":[]}`).

## Seção 4: Migração + publishing

### Seq de migração (pós-dev local)

1. Desenvolver tudo no repo atual (`~/codigo/tabelhadev/tabelhawhisper`),
   commits na main
2. Rodar CI local: `ruff format --check`, `ruff check`, `basedpyright`,
   `typos`, `vulture`, `pytest --cov`
3. Commit final + push
4. `gh repo create TAbelha/tabelhawhisper --private`
5. Push fresh: `git push https://github.com/TAbelha/tabelhawhisper.git main`
   (sem o histórico antigo)
6. `mv ~/codigo/tabelhadev/tabelhawhisper ~/codigo/tabelha/tabelhawhisper`
7. Atualizar refs locais:
   - `~/dotfiles/fish/.config/fish/functions/herdr/projects/hrtawhisper.fish`
   - `~/dotfiles/fish/.config/fish/functions/twhisper.fish`
   - `~/dotfiles/niri/.config/niri/scripts/whisper-dictate.sh`
   - Symlink DMS plugin (via install.sh, não manual)
8. Decidir com o user: deletar ou arquivar `TAbelhaDev/tabelhawhisper`

### install.sh — versão atualizada

```bash
REPO_DIR="$HOME/codigo/tabelha/tabelhawhisper"
NIRI_SCRIPTS="$HOME/.config/niri/scripts"
DMS_PLUGINS="$HOME/.config/DankMaterialShell/plugins"
CFG_DIR="$HOME/.config/tabelha/whisper-dictate"

# uv sync (cria .venv)
( cd "$REPO_DIR" && uv sync --all-groups )

# Config example
mkdir -p "$CFG_DIR"
[ ! -f "$CFG_DIR/config.toml" ] && cp "$REPO_DIR/config/whisper-dictate.toml.example" "$CFG_DIR/config.toml"

# Niri wrapper (path pro .venv Python)
mkdir -p "$NIRI_SCRIPTS"
cat > "$NIRI_SCRIPTS/whisper-dictate.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PATH="\$HOME/.local/share/mise/shims:/usr/local/bin:/usr/bin:/bin:\$PATH"
exec "$REPO_DIR/.venv/bin/python" "$REPO_DIR/bin/whisper_dictate.py" toggle
EOF
chmod +x "$NIRI_SCRIPTS/whisper-dictate.sh"

# DMS plugin symlink
mkdir -p "$DMS_PLUGINS"
ln -sfn "$REPO_DIR/dms-plugin/whisper-dictate" "$DMS_PLUGINS/whisper-dictate"
```

### Testes novos

- `tests/test_history.py`:
  - anel: inserir > history_size entradas, verificar que as mais antigas somem
  - escrita atômica: verificar que arquivo existe e é JSON válido após write
  - leitura: ler entries, verificar campos (ts, mode, state, text)
- `tests/test_pause_resume.py`:
  - pause sem recording → no-op
  - pause durante recording → state vira paused
  - resume sem paused → no-op
  - resume durante paused → state vira recording
- `tests/test_config.py` — adaptado (remove asserts de live_mode)
- `tests/test_state.py`:
  - write_state atômico: verificar que arquivo não corrompe em escrita concorrente simulada

### CI local (pré-push)

```bash
uv run ruff format --check .
uv run ruff check .
uv run basedpyright bin
uv run typos
uv run vulture bin tests --min-confidence 80
uv run pytest --cov --cov-report=term-missing
```

### Publicação no registro DMS

1. Metadata completa no manifest (repo, screenshot, startupCheck, compositors)
2. README.md com: instalação, uso, config, screenshots, link pro repo
3. Registro: submissão pro DMS plugin registry (formato do schema)
   via PR pro repo `dms-plugin-registry` quando disponível

## Restrições e limitações

- **Pausa só no wav:** streaming mode sem pausa. Botão de pausa oculto.
- **Histórico em JSON:** não é DB; não suporta busca full-text. Adequado
  pra <1000 entradas. Dados de crash podem corromper (escrita atômica mitiga).
- **Ondas em wav mode:** níveis calculados pelo Python no writer thread.
  Em streaming mode, whisper_stream.py calcula seus próprios níveis.
  Dois caminhos de cálculo, mas formato idêntico (array de floats 0..1).
- **Clipboard store:** usa wl-copy + dms ipc call em paralelo. Se DMS
  não estiver rodando, wl-copy garante funcionalidade mínima.
- **Compatibilidade:** state file antigo (sem levels, sem paused) causa
  pill silenciosa (pillVisibility ligada só a recording/transcribing).
  Caminho de upgrade limpo.
- **Pytest:** testes de pause/resume testam só lógica Python, não matam
  processos reais. Cobertura de QML: manual (pill não é unit-testável
  facilmente no CI).

## Fontes de verdade

- Screen Capture Toolbar (recPill): `/home/ianptkcs/.config/DankMaterialShell/plugins/screenCaptureToolbar/CaptureToolbar.qml`
- DMS AudioVisualization (barras): `/usr/share/quickshell/dms/quickshell/Modules/DankBar/Widgets/AudioVisualization.qml`
- DMS ClipboardButton (bar widget + popout): `/usr/share/quickshell/dms/quickshell/Modules/DankBar/Widgets/ClipboardButton.qml`
- Plugin schema (publishing): `/usr/share/quickshell/dms/quickshell/PLUGINS/plugin-schema.json`
- Plano de filtro (org move): sessão `ses_f49637a1fffe4ZYQy49LwYkBrC`
  (TAbelhaWebui, "Entendendo o projeto")
