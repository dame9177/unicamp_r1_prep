"""Revisão da curadoria (temas, classificação, adaptação das múltipla escolha).

As edições são gravadas direto nos JSON versionados de `curadoria/` e o banco é reimportado —
assim as correções podem ser commitadas.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lamina import config, importer
from lamina.db import conectar, linha, linhas

router = APIRouter(prefix="/api/curadoria")


def _ler(nome: str, padrao):
    p = config.CURADORIA_DIR / nome
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else padrao


def _gravar(nome: str, dados) -> None:
    p: Path = config.CURADORIA_DIR / nome
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dados, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


@router.get("/resumo")
def resumo():
    temas = _ler("temas.json", {"temas": []})["temas"]
    classif = _ler("questao_temas.json", {})
    adapt = _ler("adaptacoes_mc.json", {})
    with conectar() as conn:
        n = linha(conn, "SELECT COUNT(*) AS n, SUM(formato_original = 'multipla_escolha') AS mc FROM questoes")
    return {"temas": len(temas), "classificadas": len(classif), "questoes": n["n"],
            "mc_adaptadas": len(adapt), "mc_total": n["mc"]}


@router.get("/questoes")
def listar(area: str | None = None, tema_id: str | None = None, so_mc: bool = False, limite: int = 200):
    sql = ["SELECT id, area, tema_id, subtopico, tipo_cognitivo, formato_original, adaptada, enunciado, "
           "enunciado_original, alternativas_json, letra_original, resposta_esperada, aceitaveis_json "
           "FROM questoes WHERE 1=1"]
    params: list = []
    if area:
        sql.append("AND area = ?")
        params.append(area)
    if tema_id:
        sql.append("AND tema_id = ?")
        params.append(tema_id)
    if so_mc:
        sql.append("AND formato_original = 'multipla_escolha'")
    sql.append("ORDER BY processo DESC, prova_id, numero LIMIT ?")
    params.append(limite)
    with conectar() as conn:
        qs = linhas(conn, " ".join(sql), params)
    for q in qs:
        q["alternativas"] = json.loads(q.pop("alternativas_json")) if q["alternativas_json"] else None
        q["aceitaveis"] = json.loads(q.pop("aceitaveis_json") or "[]")
    return qs


class EdicaoQuestao(BaseModel):
    tema_id: str | None = None
    subtopico: str | None = None
    enunciado_discursivo: str | None = None
    resposta_esperada: str | None = None
    aceitaveis: list[str] | None = None


@router.put("/questoes/{questao_id}")
def editar(questao_id: str, dados: EdicaoQuestao):
    with conectar() as conn:
        q = linha(conn, "SELECT id, formato_original FROM questoes WHERE id = ?", (questao_id,))
        if not q:
            raise HTTPException(404, "questão não encontrada")
        if dados.tema_id and not linha(conn, "SELECT id FROM temas WHERE id = ?", (dados.tema_id,)):
            raise HTTPException(422, "tema inexistente")

    if dados.tema_id is not None or dados.subtopico is not None:
        classif = _ler("questao_temas.json", {})
        c = classif.setdefault(questao_id, {})
        if dados.tema_id is not None:
            c["tema"] = dados.tema_id
        if dados.subtopico is not None:
            c["subtopico"] = dados.subtopico
        _gravar("questao_temas.json", classif)

    if q["formato_original"] == "multipla_escolha" and (dados.enunciado_discursivo or dados.resposta_esperada):
        adapt = _ler("adaptacoes_mc.json", {})
        a = adapt.setdefault(questao_id, {})
        if dados.enunciado_discursivo:
            a["enunciado_discursivo"] = dados.enunciado_discursivo
        if dados.resposta_esperada:
            a["resposta_esperada"] = dados.resposta_esperada
        if dados.aceitaveis is not None:
            a["aceitaveis"] = dados.aceitaveis
        if not (a.get("enunciado_discursivo") and a.get("resposta_esperada")):
            raise HTTPException(422, "adaptação precisa de enunciado e resposta esperada")
        _gravar("adaptacoes_mc.json", adapt)

    with conectar() as conn:
        importer.importar(conn)
    return {"ok": True}
