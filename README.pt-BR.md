<div align="center">

# TAbelhaWhisper

**English** · [Português](README.pt-BR.md)

[![Python](https://img.shields.io/badge/python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
[![uv](https://img.shields.io/badge/uv-astro-DEA584?style=flat-square&logo=astral&logoColor=white)](https://github.com/astral-sh/uv)
[![typos](https://img.shields.io/badge/typos-checked-1B1FCA?style=flat-square)](https://github.com/astral-sh/typos)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue?style=flat-square)](LICENSE)

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/ianptkcs)

</div>

---

Ditado por voz para o [DankMaterialShell](https://github.com/TAbelhaDev/dankmaterialshell)
no niri (Wayland): aperte uma tecla, fale, e o texto transcrito vai parar na sua
área de transferência. O feedback fica na **barra dank** como um widget pequeno
que aparece só enquanto você dita, e uma **notificação silenciosa de prioridade
mínima** mostra o resultado quando você para.

Sem janelas flutuantes, sem indicadores fixos: o widget sai da barra quando
ocioso, então nunca reserva espaço.

## Como funciona

1. Um atalho do niri (padrão `Mod+E`) chama o alternador.
2. O primeiro toque inicia o `pw-record` (PipeWire) capturando seu microfone.
3. Quando você aperta de novo, a gravação para e o áudio é transcrito
   localmente com [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
4. A transcrição é copiada para a área de transferência e uma notificação de
   desktop é exibida.

Tudo roda localmente; nada é enviado para a rede.

## O widget da barra dank

O widget `TAbelhaWhisper` (um plugin do dms) lê o arquivo de estado compartilhado
e se mostra só enquanto está ativo:

- **Gravando**: ícone de microfone vermelho mais um timer `mm:ss` decorrido.
- **Transcrevendo**: ícone de microfone âmbar mais `Transcrevendo…`.
- **Ocioso / concluído**: escondido. O slot na barra colapsa, então nenhum
  espaço fica reservado.

Quando a transcrição termina, o widget some e uma notificação de desktop
**silenciosa, de prioridade mínima** (nome do app `TAbelhaWhisper`) mostra o
texto transcrito.

## Requisitos

- Linux com **PipeWire** (`pw-record`) e **WirePlumber**.
- **niri** (ou qualquer compositor que rode o script de alternância).
- **DankMaterialShell** (quickshell) para o widget da barra.
- `wl-clipboard` (`wl-copy`) para copiar para a área de transferência.
- `libnotify` (`notify-send`) para a notificação de conclusão.
- Python 3.12+ e [`uv`](https://github.com/astral-sh/uv).

## Instalação

```bash
git clone https://github.com/TAbelhaDev/tabelhawhisper
cd tabelhawhisper
./install.sh
```

O `install.sh` vai:

- sincronizar o ambiente `uv` (baixa torch + faster-whisper na primeira rodada);
- colocar um auxiliar de atalho em `~/.config/niri/scripts/whisper-dictate.sh`;
- criar um symlink do plugin do dms em `~/.config/DankMaterialShell/plugins/whisper-dictate`;
- criar `~/.config/tabelha/whisper-dictate/config.toml` a partir do exemplo, se não existir.

Depois:

1. Adicione o atalho na config do niri (o caminho do script acima):
   ```kdl
   bind Mod+E { spawn "~/.config/niri/scripts/whisper-dictate.sh"; }
   ```
2. Recarregue o dms (reinicie o quickshell) e **habilite o widget `TAbelhaWhisper`**
   nas configurações da barra.
3. Aperte `Mod+E` e comece a falar.

## Configuração

A config fica em `~/.config/tabelha/whisper-dictate/config.toml`. Veja
[`config/whisper-dictate.toml.example`](config/whisper-dictate.toml.example)
para todas as opções. Destaques:

| Chave | Padrão | Significado |
| --- | --- | --- |
| `model` | `"small"` | tamanho do modelo faster-whisper (`tiny`…`large-v3`). |
| `language` | `"auto"` | `"auto"` detecta pt/en por segmento; ou force ex. `"pt"`. |
| `device` | `"cpu"` | `"cpu"` é seguro em sistemas sem CUDA. |
| `multilingual` | `true` | habilita detecção de idioma por segmento. |
| `beam_size` | `5` | largura do beam search para mais precisão. |
| `live_mode` | `"off"` | `off` / `partial` / `streaming` (ver abaixo). |
| `copy_clipboard` | `true` | copia a transcrição para a área de transferência ao concluir. |
| `partial_interval` | `3` | segundos entre re-transcrições no modo `partial`. |

### Modos live

- **`off`** (padrão): grava e transcreve uma vez ao parar. O widget da barra
  mostra o timer; a transcrição aparece na notificação.
- **`partial`**: re-transcreve o clipe crescente a cada `partial_interval`
  segundos (mais leve que o streaming).
- **`streaming`**: um processo filho contínuo transmite o texto ao vivo para o
  arquivo de estado. Mais pesado na CPU; use quando quiser ver o texto crescer.

## Depuração

- Arquivo de estado: `/tmp/whisper-dictate.json` (`state`, `elapsed`, `start`, `text`).
- Log: `/tmp/whisper-dictate.log`.
- Processos: o gravador é `pw-record`; o orquestrador renomeia a si mesmo para
  `twhisper` (via `prctl`) para ser fácil de achar:
  ```bash
  pkill -x pw-record     # força parar uma gravação travada
  pkill -x twhisper      # força parar o orquestrador
  ```

## Desenvolvimento

```bash
uv sync --all-groups
uv run ruff format .
uv run ruff check .
uv run basedpyright bin
uv run pytest
```

## Licença

AGPL-3.0. Veja [LICENSE](LICENSE).
