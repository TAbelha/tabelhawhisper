#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
NIRI_SCRIPTS="$HOME/.config/niri/scripts"
DMS_PLUGINS="$HOME/.config/DankMaterialShell/plugins"
CFG_DIR="$HOME/.config/tabelha/whisper-dictate"
OLD_CFG_DIR="$HOME/.config/tabela/whisper-dictate"

echo "==> tabelhawhisper installer"

# Migrate config from old dir (tabela) to new dir (tabelha) if needed
if [ ! -f "$CFG_DIR/config.toml" ] && [ -f "$OLD_CFG_DIR/config.toml" ]; then
    mkdir -p "$CFG_DIR"
    cp "$OLD_CFG_DIR/config.toml" "$CFG_DIR/config.toml"
    echo "    migrated config from $OLD_CFG_DIR to $CFG_DIR"
fi

echo "==> syncing uv environment (downloads torch on first run, may take a while)"
( cd "$REPO" && uv sync --all-groups )

echo "==> niri keybind wrapper ($NIRI_SCRIPTS/whisper-dictate.sh)"
mkdir -p "$NIRI_SCRIPTS"
cat > "$NIRI_SCRIPTS/whisper-dictate.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

# niri keybind runs this without the interactive shell PATH, so make sure the
# system binaries (pw-record, wl-copy) and the mise shims are reachable.
export PATH="\$HOME/.local/share/mise/shims:/usr/local/bin:/usr/bin:/bin:\$PATH"

exec "$REPO/.venv/bin/python" "$REPO/bin/whisper_dictate.py" toggle
EOF
chmod +x "$NIRI_SCRIPTS/whisper-dictate.sh"

echo "==> dms indicator plugin"
mkdir -p "$DMS_PLUGINS"
ln -sfn "$REPO/dms-plugin/whisper-dictate" "$DMS_PLUGINS/whisper-dictate"

echo "==> config"
mkdir -p "$CFG_DIR"
if [ ! -f "$CFG_DIR/config.toml" ]; then
    cp "$REPO/config/whisper-dictate.toml.example" "$CFG_DIR/config.toml"
    echo "    created $CFG_DIR/config.toml (edit as needed)"
else
    echo "    $CFG_DIR/config.toml already exists, leaving it alone"
fi

echo
echo "Pronto. A tecla Mod+E (já configurada no niri) grava/transcreve."
echo "Recarregue o dms (restart quickshell) e habilite o widget 'TAbelha Whisper' nas configs."
