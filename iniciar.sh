#!/usr/bin/env sh
# Abre o Controle de Estoque (versão web) neste computador.
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Preparando na primeira vez..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
( sleep 2; (xdg-open http://127.0.0.1:5000 || open http://127.0.0.1:5000) >/dev/null 2>&1 ) &
exec .venv/bin/python -m estoque --banco "$HOME/estoque-almoxarifado.db" web
