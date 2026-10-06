"""Progresso reconhecido sem LLM: itens da agenda e missões ligados a blocos, temas, simulados ou
flashcards são marcados como feitos assim que o aluno cumpre o combinado, não importa por onde
respondeu as questões (no bloco, avulsas, na busca). Roda a cada ciclo do Maestro e ao abrir o
painel ou a agenda.
"""

from __future__ import annotations

import json

from lamina import consultas
from lamina.db import linha, linhas


def questoes_respondidas_do_bloco(conn, bloco_id: int) -> tuple[int, int, bool]:
    """(respondidas desde a criação do bloco, total, finalizado)."""
    r = linha(conn, """
        SELECT b.finalizado_em IS NOT NULL AS fin,
               (SELECT COUNT(*) FROM bloco_questoes bq WHERE bq.bloco_id = b.id) AS total,
               (SELECT COUNT(DISTINCT bq.questao_id) FROM bloco_questoes bq JOIN tentativas t
                  ON t.questao_id = bq.questao_id AND t.criado_em >= b.criado_em
                WHERE bq.bloco_id = b.id) AS feitas
        FROM blocos b WHERE b.id = ?""", (bloco_id,))
    if not r:
        return 0, 0, False
    return r["feitas"], r["total"], bool(r["fin"])


def bloco_concluido(conn, bloco_id: int) -> bool:
    feitas, total, fin = questoes_respondidas_do_bloco(conn, bloco_id)
    return fin or (total > 0 and feitas >= total)


def respondidas_do_tema_no_dia(conn, tema_id: str, dia: str) -> int:
    return linha(conn, """SELECT COUNT(DISTINCT t.questao_id) AS n FROM tentativas t JOIN questoes q ON q.id = t.questao_id
                          WHERE q.tema_id = ? AND date(t.criado_em, 'localtime') = ?""", (tema_id, dia))["n"]


def meta_do_tema(conn, tema_id: str, minutos: int | None) -> int:
    alvo = max(5, round(minutos / 3)) if minutos else 10  # ~3 min por questão discursiva curta
    total = linha(conn, "SELECT COUNT(*) AS n FROM questoes WHERE tema_id = ? AND anulada = 0", (tema_id,))["n"]
    return max(1, min(alvo, total))


def _cumprido(conn, item: dict, dia: str) -> bool:
    if item.get("bloco_id") and bloco_concluido(conn, item["bloco_id"]):
        return True
    tipo = item.get("tipo")
    if tipo == "simulado":
        return bool(linha(conn, "SELECT 1 AS x FROM blocos WHERE tipo = 'simulado' AND finalizado_em IS NOT NULL "
                                "AND date(finalizado_em, 'localtime') = ?", (dia,)))
    if tipo == "flashcards":
        revisou = linha(conn, "SELECT COUNT(*) AS n FROM revisoes WHERE date(revisado_em, 'localtime') = ?", (dia,))["n"]
        return revisou > 0 and consultas.flashcards_vencidos(conn) == 0
    if item.get("tema_id") and not item.get("bloco_id") and tipo in ("estudo", "revisao", None):
        return respondidas_do_tema_no_dia(conn, item["tema_id"], dia) >= meta_do_tema(conn, item["tema_id"],
                                                                                      item.get("minutos"))
    return False


def sincronizar(conn) -> int:
    """Marca como feitos os itens planejados de hoje já cumpridos. Devolve quantos mudaram."""
    hoje = linha(conn, "SELECT date('now', 'localtime') AS d")["d"]
    itens = linhas(conn, "SELECT * FROM agenda WHERE dia = ? AND status = 'planejado'", (hoje,))
    feitos = [i["id"] for i in itens if _cumprido(conn, i, hoje)]
    for i in feitos:
        conn.execute("UPDATE agenda SET status = 'feito' WHERE id = ?", (i,))
    return len(feitos)


def missao_feita(conn, missao: dict) -> bool:
    """Missão marcada pelo aluno ou cumprida (bloco/tema ligado)."""
    payload = json.loads(missao.get("payload_json") or "{}")
    if payload.get("feita"):
        return True
    hoje = linha(conn, "SELECT date('now', 'localtime') AS d")["d"]
    item = {"bloco_id": payload.get("bloco_id"), "tema_id": payload.get("tema_id"), "tipo": "estudo"}
    return (item["bloco_id"] or item["tema_id"]) is not None and _cumprido(conn, item, hoje)
