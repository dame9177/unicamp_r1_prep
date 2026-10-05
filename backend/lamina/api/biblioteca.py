"""Rotas da biblioteca compartilhada (catálogo, busca, leitura, captura manual e curadoria pelo aluno)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from lamina import config
from lamina.biblioteca import armazem
from lamina.biblioteca.captura import ErroCaptura
from lamina.db import conectar, linha

router = APIRouter(prefix="/api/biblioteca")


@router.get("")
def catalogo(tipo: str | None = None, busca: str | None = None):
    with conectar() as conn:
        itens = armazem.catalogo(conn, tipo, busca)
        tot = linha(conn, "SELECT COUNT(*) AS n, COALESCE(SUM(caracteres), 0) AS c FROM biblioteca")
    return {"itens": itens, "total": tot["n"], "caracteres": tot["c"]}


@router.get("/buscar")
def buscar(q: str, limite: int = 20, confiabilidade: str | None = None):
    with conectar() as conn:
        return armazem.buscar(conn, q, min(limite, 50), confiabilidade, por_documento=4)


def _doc(conn, doc_id: str) -> dict:
    d = armazem.obter(conn, doc_id)
    if not d:
        raise HTTPException(404, "item não encontrado")
    return d


@router.get("/{doc_id}")
def obter(doc_id: str):
    with conectar() as conn:
        return _doc(conn, doc_id)


@router.get("/{doc_id}/texto")
def texto(doc_id: str, pagina: int | None = None, ate_pagina: int | None = None, inicio: int = 0,
          max_caracteres: int = 30_000):
    with conectar() as conn:
        _doc(conn, doc_id)
        try:
            return armazem.ler(conn, doc_id, pagina, ate_pagina, None, inicio, max_caracteres, contar_acesso=False)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.get("/{doc_id}/original")
def original(doc_id: str):
    with conectar() as conn:
        d = _doc(conn, doc_id)
    pasta = config.BIBLIOTECA_DIR / "docs" / d["id"]
    arquivo = next(iter(sorted(pasta.glob("original.*"))), None) if pasta.exists() else None
    if not arquivo:
        raise HTTPException(404, "arquivo original indisponível")
    tipos = {".pdf": "application/pdf", ".html": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8"}
    return FileResponse(arquivo, media_type=tipos.get(arquivo.suffix, "application/octet-stream"),
                        content_disposition_type="inline", filename=f"{d['id']}{arquivo.suffix}")


class Captura(BaseModel):
    url: str = Field(min_length=8)
    titulo: str | None = None
    orgao: str | None = None
    ano: int | None = None
    categoria: str | None = None
    confiabilidade: str = "oficial"
    temas: list[str] = []
    resumo: str | None = None


@router.post("/capturar")
async def capturar(dados: Captura):
    try:
        return await armazem.capturar(dados.url, criado_por="aluno", titulo=dados.titulo, orgao=dados.orgao,
                                      ano=dados.ano, categoria=dados.categoria, confiabilidade=dados.confiabilidade,
                                      temas=dados.temas, resumo=dados.resumo)
    except (ErroCaptura, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


class Edicao(BaseModel):
    titulo: str | None = None
    orgao: str | None = None
    ano: int | None = None
    categoria: str | None = None
    confiabilidade: str | None = None
    resumo: str | None = None
    temas: list[str] | None = None
    status: str | None = None
    status_motivo: str | None = None


@router.patch("/{doc_id}")
def editar(doc_id: str, dados: Edicao):
    campos = dados.model_dump(exclude_unset=True)
    with conectar() as conn:
        _doc(conn, doc_id)
        try:
            if "status" in campos:
                armazem.marcar(conn, doc_id, campos.pop("status"), campos.pop("status_motivo", None) or "[aluno]")
            campos.pop("status_motivo", None)
            armazem.editar(conn, doc_id, campos)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return _doc(conn, doc_id)


@router.delete("/{doc_id}")
def remover(doc_id: str):
    with conectar() as conn:
        _doc(conn, doc_id)
        armazem.remover(conn, doc_id)
    return {"ok": True}
