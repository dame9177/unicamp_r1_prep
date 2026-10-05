#!/usr/bin/env bash
# Desenvolvimento: backend com reload (8765) + Vite com hot reload (5173).
set -euo pipefail
source "$(dirname "$0")/_ambiente.sh"
(cd "$RAIZ/backend" && uv run uvicorn lamina.main:app --host 127.0.0.1 --port 8765 --reload --reload-dir lamina) &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT
cd "$RAIZ/frontend" && npm run dev
