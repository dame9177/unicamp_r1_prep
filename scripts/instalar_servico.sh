#!/usr/bin/env bash
# Opcional: mantém a Lâmina rodando como serviço do usuário (systemd --user), iniciado no login.
# Assim o Preceptor e o bibliotecário trabalham em segundo plano mesmo com o navegador fechado.
# Desfazer: ./scripts/instalar_servico.sh --remover
set -euo pipefail
source "$(dirname "$0")/_ambiente.sh"
UNIDADE="$HOME/.config/systemd/user/lamina.service"

if [ "${1:-}" = "--remover" ]; then
  systemctl --user disable --now lamina.service 2>/dev/null || true
  rm -f "$UNIDADE"
  systemctl --user daemon-reload
  echo "Serviço removido."
  exit 0
fi

command -v systemctl >/dev/null || { echo "systemd não encontrado; use ./scripts/abrir.sh"; exit 1; }
"$RAIZ/scripts/parar.sh" >/dev/null 2>&1 || true   # libera a porta se houver um servidor avulso
mkdir -p "$(dirname "$UNIDADE")"
cat >"$UNIDADE" <<UNIT
[Unit]
Description=Lâmina — estudo para o R1 Unicamp (servidor local + Preceptor)
After=network-online.target

[Service]
Type=simple
ExecStart=$RAIZ/scripts/start.sh
Restart=on-failure
RestartSec=10
Environment=PATH=$HOME/.local/bin:$HOME/.local/share/fnm/aliases/default/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now lamina.service
echo "Serviço ativo. Status: systemctl --user status lamina · Logs: journalctl --user -u lamina -f"
