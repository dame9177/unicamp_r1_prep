#!/usr/bin/env bash
# Encerra o servidor da Lâmina iniciado em segundo plano.
pkill -f "uvicorn lamina.main:app" && echo "Lâmina encerrada." || echo "Nada rodando."
