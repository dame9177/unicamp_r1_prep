"""Acesso ao SQLite: uma conexão curta por operação, WAL para leitura concorrente."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from lamina import config

SCHEMA = Path(__file__).with_name("schema.sql")


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def conectar(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = _connect(path or config.DB_PATH)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Colunas adicionadas depois da primeira versão: (tabela, coluna, tipo).
MIGRACOES = [
    ("questoes", "obs_curadoria", "TEXT"),
    ("tentativas", "adendo", "TEXT"),
    ("chats", "agente", "TEXT NOT NULL DEFAULT 'tutor'"),
    ("llm_jobs", "fundo", "INTEGER NOT NULL DEFAULT 0"),
]


def inicializar(path: Path | None = None) -> None:
    with conectar(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        for tabela, coluna, tipo in MIGRACOES:
            existentes = {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}
            if coluna not in existentes:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")


def linhas(conn: sqlite3.Connection, sql: str, params: Any = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def linha(conn: sqlite3.Connection, sql: str, params: Any = ()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def obter_ajuste(conn: sqlite3.Connection, chave: str, padrao: Any = None) -> Any:
    r = conn.execute("SELECT valor_json FROM ajustes WHERE chave = ?", (chave,)).fetchone()
    return json.loads(r[0]) if r else padrao


def salvar_ajuste(conn: sqlite3.Connection, chave: str, valor: Any) -> None:
    conn.execute(
        "INSERT INTO ajustes (chave, valor_json) VALUES (?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor_json = excluded.valor_json",
        (chave, json.dumps(valor, ensure_ascii=False)),
    )


def obter_estado(conn: sqlite3.Connection, chave: str, padrao: Any = None) -> Any:
    r = conn.execute("SELECT valor_json FROM estado WHERE chave = ?", (chave,)).fetchone()
    return json.loads(r[0]) if r else padrao


def salvar_estado(conn: sqlite3.Connection, chave: str, valor: Any) -> None:
    conn.execute(
        "INSERT INTO estado (chave, valor_json) VALUES (?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor_json = excluded.valor_json",
        (chave, json.dumps(valor, ensure_ascii=False)),
    )
