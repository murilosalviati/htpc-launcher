#!/usr/bin/env bash
# Instala (ou atualiza) a extensão HTPC Launcher Bridge para o usuário atual.
set -euo pipefail

UUID="htpc-launcher@htpc"
SRC="$(cd "$(dirname "$0")" && pwd)/$UUID"
DEST="$HOME/.local/share/gnome-shell/extensions/$UUID"

mkdir -p "$DEST"
cp "$SRC/metadata.json" "$SRC/extension.js" "$DEST/"
echo "Arquivos copiados para $DEST"

if gnome-extensions info "$UUID" >/dev/null 2>&1; then
    gnome-extensions enable "$UUID"
    echo "Extensão ativada."
    echo "Se era uma atualização: saia da sessão e entre de novo para o GNOME carregar o código novo."
else
    echo
    echo "No Wayland o GNOME só enxerga extensões novas depois de um novo login."
    echo "1. Saia da sessão e entre de novo (no servidor: sudo systemctl restart gdm — fecha tudo o que estiver aberto)."
    echo "2. Rode: gnome-extensions enable $UUID"
fi
