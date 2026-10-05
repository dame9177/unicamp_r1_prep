#!/usr/bin/env bash
# Encerra o servidor da Lâmina iniciado em segundo plano.
if systemctl --user is-active --quiet lamina.service 2>/dev/null; then
  systemctl --user stop lamina.service && echo "Serviço da Lâmina parado (volta no próximo login; para remover: instalar_servico.sh --remover)."
  exit 0
fi
pkill -f "uvicorn lamina.main:app" && echo "Lâmina encerrada." || echo "Nada rodando."
