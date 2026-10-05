"""Caminhos e constantes da aplicação.

Tudo que é pessoal (banco, perfil, sessões do Claude) vive em `app_data/`, que é ignorado pelo git.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BANCO_DIR = REPO_ROOT / "banco_questoes"
QUESTOES_JSONL = BANCO_DIR / "data" / "questoes.jsonl"
CURADORIA_DIR = REPO_ROOT / "curadoria"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

APP_DATA = Path(os.environ.get("LAMINA_DATA_DIR", REPO_ROOT / "app_data"))
DB_PATH = APP_DATA / "lamina.db"
PERFIL_PATH = APP_DATA / "perfil.json"
CLAUDE_CWD = APP_DATA / "claude_cwd"

CLAUDE_CLI = Path(os.environ.get("LAMINA_CLAUDE_CLI", Path.home() / ".local" / "bin" / "claude"))

AREAS = ["Clínica Médica", "Cirurgia", "Pediatria", "Ginecologia e Obstetrícia", "Saúde Coletiva"]

PERFIL_PADRAO = {
    "nome": "",
    "especialidade_alvo": "",
    "data_prova": "2026-11-15",
    "instituicao": "Unicamp — Residência Médica, Acesso Direto",
}


def carregar_perfil() -> dict:
    perfil = dict(PERFIL_PADRAO)
    if PERFIL_PATH.exists():
        perfil.update(json.loads(PERFIL_PATH.read_text(encoding="utf-8")))
    return perfil


def salvar_perfil(perfil: dict) -> None:
    APP_DATA.mkdir(parents=True, exist_ok=True)
    PERFIL_PATH.write_text(json.dumps(perfil, ensure_ascii=False, indent=2), encoding="utf-8")


def data_prova() -> date:
    return date.fromisoformat(carregar_perfil()["data_prova"])


def dias_ate_prova(hoje: date | None = None) -> int:
    return (data_prova() - (hoje or date.today())).days
