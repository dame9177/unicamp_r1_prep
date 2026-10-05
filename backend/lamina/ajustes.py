"""Ajustes do usuário (modelos por papel, esforço, automações). Padrões calibrados para plano Pro."""

from __future__ import annotations

import sqlite3

from lamina.db import obter_ajuste, salvar_ajuste

PADROES: dict[str, object] = {
    "modelos": {
        "juiz": "claude-haiku-4-5",
        "juiz_revisao": "claude-sonnet-5-5",
        "tutor": "claude-sonnet-5-5",
        "flashcards": "claude-sonnet-5-5",
        "preceptor": "claude-sonnet-5-5",
        "bibliotecario": "claude-sonnet-5-5",
        "curadoria": "claude-sonnet-5-5",
    },
    "esforco": {"tutor": "low", "flashcards": "low", "preceptor": "medium", "bibliotecario": "medium",
                "curadoria": "medium", "juiz_revisao": "medium"},
    "correcao_automatica": True,
    # Preceptor (orquestrador em segundo plano)
    "preceptor_fundo": True,            # rondas e tarefas automáticas enquanto o servidor estiver rodando
    "orcamento_fundo_dia": 400_000,     # tokens/dia que o segundo plano pode gastar
    "limiar_janela": 0.7,               # não roda em segundo plano acima desta fração da janela do plano
    "hora_ronda": 7,                    # primeira ronda do dia a partir desta hora
    "max_rondas_dia": 3,
    "coach_min_tentativas_novas": 25,   # respostas novas que justificam uma ronda extra
    "notificacoes_desktop": True,
    "hora_lembrete": 19,                # lembretes automáticos (meta do dia, flashcards)
    "silencio": [23, 7],                # sem notificações neste intervalo
    "simulado_duracao_min": 240,
    "meta_diaria": 25,
    "aviso_tokens_dia": 400_000,
}

MODELOS_DISPONIVEIS = [
    {"id": "claude-haiku-4-5", "nome": "Haiku 4.5 (econômico)"},
    {"id": "claude-sonnet-5-5", "nome": "Sonnet 5.5 (equilibrado)"},
    {"id": "claude-opus-5-5", "nome": "Opus 5.5 (máxima qualidade, consome mais)"},
]


def todos(conn: sqlite3.Connection) -> dict:
    saida = {}
    for chave, padrao in PADROES.items():
        valor = obter_ajuste(conn, chave, padrao)
        if isinstance(padrao, dict):
            valor = {**padrao, **(valor or {})}
        saida[chave] = valor
    return saida


def obter(conn: sqlite3.Connection, chave: str):
    return todos(conn)[chave]


def modelo(conn: sqlite3.Connection, papel: str) -> str:
    return todos(conn)["modelos"][papel]


def esforco(conn: sqlite3.Connection, papel: str) -> str | None:
    return todos(conn)["esforco"].get(papel)


def atualizar(conn: sqlite3.Connection, novos: dict) -> dict:
    for chave, valor in novos.items():
        if chave not in PADROES:
            raise KeyError(chave)
        salvar_ajuste(conn, chave, valor)
    return todos(conn)
