#!/usr/bin/env bash
# Cria o atalho "Lâmina" no menu de aplicativos (Linux/freedesktop).
set -euo pipefail
source "$(dirname "$0")/_ambiente.sh"
DESTINO="$HOME/.local/share/applications/lamina.desktop"
mkdir -p "$(dirname "$DESTINO")"
cat >"$DESTINO" <<DESK
[Desktop Entry]
Type=Application
Name=Lâmina
Comment=Estudo para o R1 de Acesso Direto da Unicamp
Exec=$RAIZ/scripts/abrir.sh
Icon=$RAIZ/frontend/public/favicon.svg
Terminal=false
Categories=Education;
DESK
chmod +x "$DESTINO"
command -v update-desktop-database >/dev/null && update-desktop-database "$(dirname "$DESTINO")" >/dev/null 2>&1 || true
echo "Atalho criado: $DESTINO"
