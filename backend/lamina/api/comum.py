"""Utilidades compartilhadas pelas rotas."""

from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache

from fastapi import HTTPException

from lamina import config
from lamina.db import linha
from lamina.importer import precisa_alternativas

log = logging.getLogger("lamina")
_tarefas: set[asyncio.Task] = set()


def em_segundo_plano(coro) -> asyncio.Task:
    """Dispara uma corrotina sem bloquear a resposta HTTP (mantém referência para não ser coletada)."""
    t = asyncio.create_task(coro)
    _tarefas.add(t)

    def _fim(task: asyncio.Task) -> None:
        _tarefas.discard(task)
        if not task.cancelled() and task.exception():
            log.warning("tarefa em segundo plano falhou: %s", task.exception())

    t.add_done_callback(_fim)
    return t


def obter_ou_404(conn, sql: str, params, oque: str = "registro") -> dict:
    r = linha(conn, sql, params)
    if not r:
        raise HTTPException(404, f"{oque} não encontrado")
    return r


def imagens_publicas(imagens_json: str) -> list[dict]:
    return [
        {"url": "/imagens/" + img["arquivo"].removeprefix("images/"), "legenda": img.get("legenda"),
         "rotulo": img.get("rotulo")}
        for img in json.loads(imagens_json or "[]")
    ]


def resumo_tentativa(t: dict | None) -> dict | None:
    if not t:
        return None
    return {k: t.get(k) for k in ("id", "questao_id", "bloco_id", "resposta", "confianca", "veredito",
                                  "fonte_veredito", "justificativa", "faltou", "resposta_modelo", "adendo", "tempo_seg",
                                  "criado_em", "julgado_em")}


def gabarito(q: dict) -> dict:
    return {
        "resposta_esperada": q["resposta_esperada"],
        "aceitaveis": json.loads(q["aceitaveis_json"] or "[]"),
        "ampliado": bool(q["ampliado"]),
        "adaptada": bool(q["adaptada"]),
        "nota_atualizacao": q.get("obs_curadoria"),
        "letra_original": q["letra_original"],
        "alternativas_originais": json.loads(q["alternativas_json"]) if q["alternativas_json"] else None,
        "enunciado_original": q["enunciado_original"] if q["adaptada"] else None,
    }


def questao_publica(conn, q: dict, revelar: bool) -> dict:
    tema = linha(conn, "SELECT nome FROM temas WHERE id = ?", (q["tema_id"],))
    ultima = linha(conn, "SELECT * FROM tentativas WHERE questao_id = ? ORDER BY id DESC LIMIT 1", (q["id"],))
    n = linha(conn, "SELECT COUNT(*) AS n FROM tentativas WHERE questao_id = ?", (q["id"],))["n"]
    nota = linha(conn, "SELECT explicacao_md, fixada_em FROM questao_notas WHERE questao_id = ?", (q["id"],))
    mc_sem_adaptacao = q["formato_original"] == "multipla_escolha" and not q["adaptada"]
    alternativas = None
    if mc_sem_adaptacao and precisa_alternativas(q["enunciado"]):
        alternativas = json.loads(q["alternativas_json"] or "{}")
    return {
        "id": q["id"],
        "prova_id": q["prova_id"],
        "processo": q["processo"],
        "turno": q["turno"],
        "numero": q["numero"],
        "area": q["area"],
        "tema_id": q["tema_id"],
        "tema_nome": tema["nome"] if tema else None,
        "subtopico": q["subtopico"],
        "tipo_cognitivo": q["tipo_cognitivo"],
        "formato_original": q["formato_original"],
        "adaptada": bool(q["adaptada"]),
        "alternativas_provisorias": alternativas,
        "enunciado_compartilhado": q["enunciado_compartilhado"],
        "enunciado": q["enunciado"],
        "imagens": imagens_publicas(q["imagens_json"]),
        "fonte": json.loads(q["fonte_json"]) if q["fonte_json"] else None,
        "anulada": bool(q["anulada"]),
        "n_tentativas": n,
        "ultima_tentativa": resumo_tentativa(ultima),
        "explicacao": nota if nota and nota.get("explicacao_md") else None,
        "gabarito": gabarito(q) if revelar else None,
    }


@lru_cache(maxsize=32)
def valores_referencia(prova_id: str) -> str | None:
    arquivo = config.BANCO_DIR / "data" / f"{prova_id.removeprefix('unicamp-')}.json"
    if not arquivo.exists():
        return None
    return json.loads(arquivo.read_text(encoding="utf-8")).get("valores_referencia")
