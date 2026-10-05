#!/usr/bin/env bash
# Instala as dependências do backend (uv) e do frontend (npm).
set -euo pipefail
source "$(dirname "$0")/_ambiente.sh"
command -v uv >/dev/null || { echo "uv não encontrado: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
command -v npm >/dev/null || { echo "Node não encontrado: instale via fnm (https://github.com/Schniz/fnm)"; exit 1; }
(cd "$RAIZ/backend" && uv sync)
(cd "$RAIZ/frontend" && npm install)
mkdir -p "$RAIZ/app_data"
[ -f "$RAIZ/app_data/perfil.json" ] || cp "$RAIZ/perfil.example.json" "$RAIZ/app_data/perfil.json"
echo "Pronto. Faça login no Claude CLI uma vez (fora de outras sessões do Claude): claude auth login"
