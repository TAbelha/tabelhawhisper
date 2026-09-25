#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
NIRI_SCRIPTS="$HOME/.config/niri/scripts"
DMS_PLUGINS="$HOME/.config/DankMaterialShell/plugins"
CFG_DIR="$HOME/.config/tabelha/tabelhawhisper"

echo "==> tabelhawhisper installer"

# One-time migration from legacy config dirs (newest first); mv keeps history.json and perms
for old in "$HOME/.config/tabelha/whisper-dictate" "$HOME/.config/tabela/whisper-dictate"; do
    if [ ! -e "$CFG_DIR" ] && [ -d "$old" ]; then
        mkdir -p "$(dirname "$CFG_DIR")"
        mv "$old" "$CFG_DIR"
        echo "    migrated $old -> $CFG_DIR"
    fi
done

echo "==> syncing uv environment (downloads torch on first run, may take a while)"
( cd "$REPO" && uv sync --all-groups )

echo "==> niri keybind wrapper ($NIRI_SCRIPTS/tabelhawhisper.sh)"
mkdir -p "$NIRI_SCRIPTS"
cat > "$NIRI_SCRIPTS/tabelhawhisper.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PATH="\$HOME/.local/share/mise/shims:/usr/local/bin:/usr/bin:/bin:\$PATH"
exec "$REPO/.venv/bin/python" "$REPO/bin/tabelhawhisper.py" toggle
EOF
chmod +x "$NIRI_SCRIPTS/tabelhawhisper.sh"

echo "==> dms plugin (composite: daemon pill + widget history)"
mkdir -p "$DMS_PLUGINS"
ln -sfn "$REPO/dms-plugin/tabelhawhisper" "$DMS_PLUGINS/tabelhawhisper"

# Remove legacy symlink and niri wrapper from before the rename
if [ -L "$DMS_PLUGINS/whisper-dictate" ]; then
    rm "$DMS_PLUGINS/whisper-dictate"
    echo "    removed legacy $DMS_PLUGINS/whisper-dictate"
fi
if [ -f "$NIRI_SCRIPTS/whisper-dictate.sh" ] && grep -q whisper_dictate.py "$NIRI_SCRIPTS/whisper-dictate.sh"; then
    rm "$NIRI_SCRIPTS/whisper-dictate.sh"
    echo "    removed legacy $NIRI_SCRIPTS/whisper-dictate.sh (point your Mod+E bind at tabelhawhisper.sh)"
fi

echo "==> config"
mkdir -p "$CFG_DIR"
if [ ! -f "$CFG_DIR/config.toml" ]; then
    cp "$REPO/config/tabelhawhisper.toml.example" "$CFG_DIR/config.toml"
    echo "    created $CFG_DIR/config.toml (edit as needed)"
else
    echo "    $CFG_DIR/config.toml already exists, leaving it alone"
fi

echo
echo "Pronto. A tecla Mod+E grava/transcreve."
echo "Pill flutuante aparece durante gravacao. Widget na barra mostra historico."
echo "Recarregue o dms e habilite o plugin 'TAbelhaWhisper' nas configs."
