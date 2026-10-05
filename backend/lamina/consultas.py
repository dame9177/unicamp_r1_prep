"""Consultas agregadas (desempenho por questão, tema, área, bloco). Usadas pela API e pelo coach."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import UTC, datetime

from lamina import config
from lamina.db import linha, linhas
from lamina.domain.mastery import Estatistica
from lamina.domain.priority import normalizar, prioridade

SQL_ULTIMAS = """
SELECT q.id AS questao_id, q.tema_id, q.area, q.peso_prevalencia, q.processo,
       t.id AS tentativa_id, t.veredito, t.confianca, t.criado_em
FROM questoes q
LEFT JOIN (
  SELECT * FROM (
    SELECT tt.*, ROW_NUMBER() OVER (PARTITION BY tt.questao_id ORDER BY tt.criado_em DESC, tt.id DESC) AS rn
    FROM tentativas tt WHERE tt.veredito IN ('correto', 'parcial', 'incorreto')
  ) WHERE rn = 1
) t ON t.questao_id = q.id
WHERE q.anulada = 0
"""


def ultimas_tentativas(conn: sqlite3.Connection) -> list[dict]:
    return linhas(conn, SQL_ULTIMAS)


def _agrupar(rows: list[dict], chave: str) -> dict[str, Estatistica]:
    grupos: dict[str, Estatistica] = defaultdict(Estatistica)
    for r in rows:
        grupos[r[chave]].adicionar(r["questao_id"], r["veredito"], r["confianca"], r["criado_em"])
    return grupos


def estatisticas_temas(conn: sqlite3.Connection) -> list[dict]:
    rows = ultimas_tentativas(conn)
    por_tema = _agrupar(rows, "tema_id")
    prevalencia: dict[str, float] = defaultdict(float)
    for r in rows:
        prevalencia[r["tema_id"]] += r["peso_prevalencia"]
    prev_norm = normalizar(dict(prevalencia))

    temas = linhas(conn, "SELECT * FROM temas ORDER BY ordem, nome")
    saida = []
    for t in temas:
        est = por_tema.get(t["id"])
        if not est or est.total == 0:
            continue
        resumo = est.resumo(t["status_manual"])
        pn = prev_norm.get(t["id"], 0.0)
        saida.append({
            **t,
            **resumo,
            "geral": t["id"].endswith("--geral"),
            "prevalencia": round(prevalencia[t["id"]], 3),
            "prevalencia_norm": round(pn, 4),
            "prioridade": round(prioridade(pn, est.aproveitamento_firme, t["peso_coach"]), 4),
        })
    return saida


def estatisticas_areas(conn: sqlite3.Connection) -> list[dict]:
    por_area = _agrupar(ultimas_tentativas(conn), "area")
    return [{"area": a, **por_area[a].resumo()} for a in config.AREAS if a in por_area]


def estatistica_de(conn: sqlite3.Connection, questao_ids: list[str]) -> dict:
    ids = set(questao_ids)
    est = Estatistica()
    for r in ultimas_tentativas(conn):
        if r["questao_id"] in ids:
            est.adicionar(r["questao_id"], r["veredito"], r["confianca"], r["criado_em"])
    return est.resumo()


def questoes_refazer(conn: sqlite3.Connection, questao_ids: list[str]) -> list[str]:
    ids = set(questao_ids)
    est = Estatistica()
    for r in ultimas_tentativas(conn):
        if r["questao_id"] in ids:
            est.adicionar(r["questao_id"], r["veredito"], r["confianca"], r["criado_em"])
    return est.questoes_refazer


def flashcards_vencidos(conn: sqlite3.Connection) -> int:
    agora = datetime.now(UTC).isoformat()
    r = linha(conn, "SELECT COUNT(*) AS n FROM flashcards WHERE suspenso = 0 AND due <= ?", (agora,))
    return r["n"] if r else 0


def totais(conn: sqlite3.Connection) -> dict:
    t = linha(conn, """
        SELECT COUNT(*) AS tentativas,
               SUM(veredito = 'correto') AS corretas,
               SUM(veredito = 'parcial') AS parciais,
               SUM(veredito = 'incorreto') AS incorretas,
               SUM(confianca = 'chute') AS chutes,
               COUNT(DISTINCT questao_id) AS questoes_distintas,
               SUM(date(criado_em) = date('now')) AS hoje
        FROM tentativas WHERE veredito IN ('correto', 'parcial', 'incorreto')""")
    n_questoes = linha(conn, "SELECT COUNT(*) AS n FROM questoes WHERE anulada = 0")["n"]
    return {**{k: (v or 0) for k, v in t.items()}, "questoes_banco": n_questoes}


def serie_diaria(conn: sqlite3.Connection, dias: int = 21) -> list[dict]:
    return linhas(conn, """
        SELECT date(criado_em) AS dia, COUNT(*) AS n,
               SUM(CASE veredito WHEN 'correto' THEN 1.0 WHEN 'parcial' THEN 0.5 ELSE 0 END) AS pontos
        FROM tentativas
        WHERE veredito IN ('correto', 'parcial', 'incorreto') AND criado_em >= date('now', ?)
        GROUP BY dia ORDER BY dia""", (f"-{dias} days",))
