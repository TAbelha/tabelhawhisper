<div align="center">

# tabelhawhisper

**Ditado local por voz no Linux: aperta a tecla, fala, o texto cai no clipboard.**

[English](README.md) · **Português**

[![Python](https://img.shields.io/badge/python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
[![uv](https://img.shields.io/badge/uv-astro-DEA584?style=flat-square&logo=astral&logoColor=white)](https://github.com/astral-sh/uv)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue?style=flat-square)](LICENSE)

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/ianptkcs)

</div>

---

## O que é

Plugin de ditado por voz pro
[DankMaterialShell](https://github.com/AvengeMedia/DankMaterialShell):
grava áudio, transcreve localmente com
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), copia pro
clipboard — com overlay flutuante (pílula) e widget de histórico de
transcrições. Sem nuvem, sem API keys, tudo roda na sua máquina.

## Como funciona

1. Aperte **Mod+E** pra começar/parar a gravação (modo wav grava em arquivo
   com pausa; modo streaming canaliza o áudio sem pausa).
2. Uma pílula flutuante mostra status de gravação/pausa/transcrição com
   barras de onda em tempo real (níveis PCM de verdade do mic), timer e
   controles.
3. Aperte parar pra finalizar: o faster-whisper transcreve localmente e o
   texto é copiado automaticamente pro clipboard (mais clipboard service do
   DMS e `wl-copy`).
   No modo wav a gravação entra numa fila, então dá pra começar a próxima na
   hora; a pílula mostra quantas ainda estão sendo transcritas.
4. Transcrições passadas ficam no widget de histórico na barra do DMS
   (ring buffer persistente, clique pra expandir e copiar).

As barras de onda seguem a sua voz, não o som de fundo constante: um noise
gate aprende o piso do ambiente (música nas caixas de som, ventoinha) e só
mostra o que passa dele. O gate mexe só nas barras, não na transcrição.

## Configuração

`~/.config/tabelha/tabelhawhisper/config.toml` (veja
[`config/tabelhawhisper.toml.example`](config/tabelhawhisper.toml.example)).
Além de modelo/idioma/modo:

| Chave | Padrão | O que faz |
| --- | --- | --- |
| `save_audio` | `false` | Guarda uma cópia de cada gravação (modo wav). Desligado = nunca salva. |
| `save_audio_dir` | `""` | Onde salvar; vazio = `~/.local/share/tabelha/tabelhawhisper/recordings`. |
| `send_to_agent` | `false` | Envia a transcrição pro painel de agente focado no herdr. |

### Enviar pra um agente no herdr

Pare a gravação com `tabelhawhisper.sh --send` (por exemplo num bind
`Mod+Shift+E`) e a transcrição é digitada no painel de agente do herdr que
estava focado naquele momento e enviada com Enter, mesmo que você troque de
janela no meio tempo. O alvo precisa ser uma única janela de terminal com uma
sessão herdr cujo painel focado seja um agente (Claude, opencode…). Se não
for, ou se o agente estiver esperando aprovação, o texto fica no clipboard e
a notificação diz por que não enviou. `--no-send` ignora
`send_to_agent = true` numa gravação específica.

Cuidado: o niri padrão usa `Mod+Shift+E` pra sair da sessão.

## Rodando localmente

Requisitos: Python 3.12+, PipeWire (`pw-record`), DankMaterialShell (pra
pílula e o widget de histórico), `notify-send` e `wl-clipboard`.

```bash
git clone https://github.com/TAbelha/tabelhawhisper.git
cd tabelhawhisper
./install.sh
```

O instalador sincroniza o ambiente uv (faster-whisper, numpy, etc.),
configura o atalho do niri (`Mod+E`), cria o symlink do plugin DMS e cria o
arquivo de config em `~/.config/tabelha/tabelhawhisper/config.toml`.

## Desenvolvimento

O plugin é um plugin DMS **composto** com dois componentes:

- **DictatePill.qml** (daemon): overlay flutuante com controles de
  gravação, barras de onda e status de transcrição.
- **HistoryWidget.qml** (widget da barra): ícone de histórico na barra,
  popout com entradas expansíveis e cópia.

## Changelog

Veja [CHANGELOG.md](CHANGELOG.md) para o histórico de versões.

## Apoie o projeto

- **Global**: [ko-fi.com/ianptkcs](https://ko-fi.com/ianptkcs)
- **Brasil (Pix)**: escaneie o QR abaixo ou copie o código

  <img src="pix-qr.png" alt="Pix QR" width="200" />

  <details><summary>Código Pix (copiar)</summary>

  ```
  00020126580014BR.GOV.BCB.PIX01365ad933b0-dcdc-4525-a736-0759902aeec65204000053039865802BR5925Ian Patrick da Costa Soar6009SAO PAULO62140510tQA85x6Dov63041FB6
  ```

  </details>

## Licença

[AGPL-3.0](LICENSE) — copyleft forte: você pode usar, modificar e até
hospedar o tabelhawhisper comercialmente, mas qualquer versão modificada,
incluindo uma rodando como serviço de rede (SaaS), tem que continuar open
source sob a mesma licença.
