#!/usr/bin/env bash
# Uso normal: gera o frontend (se mudou) e sobe tudo em http://127.0.0.1:8765
set -euo pipefail
source "$(dirname "$0")/_ambiente.sh"
cd "$RAIZ/frontend"
if [ ! -d dist ] || [ -n "$(find src index.html -newer dist -print -quit 2>/dev/null)" ]; then
  npm run build
fi
cd "$RAIZ/backend"
echo "Lâmina em http://127.0.0.1:8765"
exec uv run uvicorn lamina.main:app --host 127.0.0.1 --port 8765
