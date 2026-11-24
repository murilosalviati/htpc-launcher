#!/usr/bin/env bash
# Instala (ou atualiza) o serviço do controle do HTPC para o usuário atual.
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
DADOS="$HOME/.local/share/htpc-launcher"
CONFIG="$HOME/.config/htpc-launcher"
UNIDADES="$HOME/.config/systemd/user"

if ! python3 -c 'import evdev, jeepney' 2>/dev/null; then
    echo "Instalando python3-evdev e python3-jeepney (pede a senha do sudo)..."
    sudo apt install -y python3-evdev python3-jeepney
fi

mkdir -p "$DADOS" "$CONFIG" "$UNIDADES"
cp "$AQUI/controle.py" "$DADOS/"

if [ -f "$CONFIG/apps.json" ]; then
    echo "Mantido o $CONFIG/apps.json que já existia."
else
    cp "$AQUI/../config/apps.json" "$CONFIG/"
    echo "Criado $CONFIG/apps.json"
fi

cp "$AQUI/htpc-controle.service" "$UNIDADES/"
systemctl --user daemon-reload
systemctl --user enable htpc-controle.service
systemctl --user restart htpc-controle.service

echo
echo "Serviço rodando. Para acompanhar o que ele faz:"
echo "  journalctl --user -fu htpc-controle"
