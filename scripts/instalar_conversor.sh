#!/usr/bin/env bash
# Opcional: conversor local de PDF/imagem → Markdown na GPU (Marker), isolado do app como ferramenta do uv.
# Dá à biblioteca Markdown com títulos e tabelas e OCR de PDFs escaneados, sem gastar tokens.
# Ocupa ~4 GB em disco (PyTorch com CUDA) + ~3,3 GB de modelos (baixados na 1ª conversão) e até ~6,5 GB de VRAM.
# Versão 1.x de propósito: o Marker 2 exige um servidor de inferência à parte (vLLM via Docker ou llama.cpp).
# Desfazer: uv tool uninstall marker-pdf
set -euo pipefail
source "$(dirname "$0")/_ambiente.sh"
uv tool install --python 3.12 --torch-backend auto "marker-pdf==1.10.2"
"$HOME/.local/share/uv/tools/marker-pdf/bin/python" -c \
  "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '(CPU)')"
echo "Conversor instalado. Reinicie a Lâmina (systemctl --user restart lamina ou ./scripts/start.sh)."
