#!/usr/bin/env bash
# Instala (ou atualiza) o launcher do HTPC e faz ele abrir sozinho no login.
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
DADOS="$HOME/.local/share/htpc-launcher"
CONFIG="$HOME/.config/htpc-launcher"

faltando=()
python3 -c 'import gi; gi.require_version("Gtk", "4.0")' 2>/dev/null || faltando+=(python3-gi gir1.2-gtk-4.0)
python3 -c 'import evdev' 2>/dev/null || faltando+=(python3-evdev)
if [ ${#faltando[@]} -gt 0 ]; then
    echo "Instalando ${faltando[*]} (pede a senha do sudo)..."
    sudo apt install -y "${faltando[@]}"
fi

mkdir -p "$DADOS" "$CONFIG" "$HOME/.local/share/applications" "$HOME/.config/autostart"
cp "$AQUI/launcher.py" "$AQUI/launcher.css" "$DADOS/"

if [ ! -f "$CONFIG/apps.json" ]; then
    cp "$AQUI/../config/apps.json" "$CONFIG/"
    echo "Criado $CONFIG/apps.json"
fi

# O serviço do controle usa este comando para abrir o launcher se ele não estiver aberto.
python3 - "$CONFIG/apps.json" "$DADOS/launcher.py" <<'EOF'
import json, sys
caminho, launcher = sys.argv[1:]
with open(caminho, encoding="utf-8") as f:
    cfg = json.load(f)
cfg.setdefault("launcher", {})["abrir"] = ["python3", launcher]
cfg["launcher"].setdefault("id", "htpc-launcher")
with open(caminho, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")
EOF

sed "s|@DADOS@|$DADOS|g" "$AQUI/htpc-launcher.desktop.in" > "$HOME/.local/share/applications/htpc-launcher.desktop"
cp "$HOME/.local/share/applications/htpc-launcher.desktop" "$HOME/.config/autostart/"

echo "Launcher instalado. Ele abre sozinho no próximo login."
echo "Para abrir agora, na sessão da TV: gtk-launch htpc-launcher"
