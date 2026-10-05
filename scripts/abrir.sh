#!/usr/bin/env bash
# Abre a Lâmina no navegador, subindo o servidor em segundo plano se ainda não estiver rodando.
set -euo pipefail
source "$(dirname "$0")/_ambiente.sh"
URL="http://127.0.0.1:8765"
if ! curl -fsS "$URL/api/saude" >/dev/null 2>&1; then
  mkdir -p "$RAIZ/app_data"
  if [ -f "$HOME/.config/systemd/user/lamina.service" ]; then
    systemctl --user start lamina.service
  else
    nohup "$RAIZ/scripts/start.sh" >"$RAIZ/app_data/servidor.log" 2>&1 &
  fi
  for _ in $(seq 1 60); do
    curl -fsS "$URL/api/saude" >/dev/null 2>&1 && break
    sleep 1
  done
fi
xdg-open "$URL" >/dev/null 2>&1 || echo "Abra $URL no navegador."
