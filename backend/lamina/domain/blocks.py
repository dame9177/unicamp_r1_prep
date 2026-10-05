"""Montagem de blocos de questões (por tema, refazer, simulado, custom)."""

from __future__ import annotations

import json
import random
import sqlite3

from lamina import config
from lamina.consultas import questoes_refazer, ultimas_tentativas
from lamina.db import linhas


def questoes_do_tema(conn: sqlite3.Connection, tema_id: str) -> list[str]:
    rows = linhas(
        conn,
        "SELECT id FROM questoes WHERE tema_id = ? AND anulada = 0 ORDER BY processo DESC, prova_id, numero",
        (tema_id,),
    )
    return [r["id"] for r in rows]


def ordenar_nao_respondidas_primeiro(conn: sqlite3.Connection, ids: list[str]) -> list[str]:
    respondidas = {r["questao_id"] for r in ultimas_tentativas(conn) if r["veredito"]}
    return [i for i in ids if i not in respondidas] + [i for i in ids if i in respondidas]


def selecionar_simulado(conn: sqlite3.Connection, por_area: int = 10, semente: int | None = None) -> list[str]:
    """10 questões por área, na ordem da prova; prioriza inéditas, depois as mais antigas."""
    rnd = random.Random(semente)
    rows = ultimas_tentativas(conn)
    selecionadas: list[str] = []
    for area in config.AREAS:
        candidatas = [r for r in rows if r["area"] == area]
        rnd.shuffle(candidatas)
        candidatas.sort(key=lambda r: (r["criado_em"] is not None, r["criado_em"] or ""))
        selecionadas += [r["questao_id"] for r in candidatas[:por_area]]
    return selecionadas


def criar_bloco(
    conn: sqlite3.Connection,
    nome: str,
    tipo: str,
    questao_ids: list[str],
    tema_id: str | None = None,
    descricao: str | None = None,
    criado_por: str = "user",
    config_bloco: dict | None = None,
) -> int:
    if not questao_ids:
        raise ValueError("bloco sem questões")
    cur = conn.execute(
        "INSERT INTO blocos (nome, tipo, tema_id, descricao, criado_por, config_json) VALUES (?, ?, ?, ?, ?, ?)",
        (nome, tipo, tema_id, descricao, criado_por, json.dumps(config_bloco or {}, ensure_ascii=False)),
    )
    bloco_id = cur.lastrowid
    vistos: set[str] = set()
    ordem = 0
    for qid in questao_ids:
        if qid in vistos:
            continue
        vistos.add(qid)
        conn.execute(
            "INSERT INTO bloco_questoes (bloco_id, questao_id, ordem) VALUES (?, ?, ?)", (bloco_id, qid, ordem)
        )
        ordem += 1
    return bloco_id


def ids_do_bloco(conn: sqlite3.Connection, bloco_id: int) -> list[str]:
    return [r["questao_id"] for r in linhas(
        conn, "SELECT questao_id FROM bloco_questoes WHERE bloco_id = ? ORDER BY ordem", (bloco_id,))]


def refazer_ids(conn: sqlite3.Connection, ids: list[str]) -> list[str]:
    alvo = set(questoes_refazer(conn, ids))
    return [i for i in ids if i in alvo]
