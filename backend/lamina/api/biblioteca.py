"""Rotas da biblioteca compartilhada (catálogo, busca, leitura, captura manual e curadoria pelo aluno)."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from lamina import config
from lamina.biblioteca import armazem, captura, conversor
from lamina.biblioteca.captura import ErroCaptura
from lamina.db import conectar, linha

router = APIRouter(prefix="/api/biblioteca")


@router.get("")
def catalogo(tipo: str | None = None, busca: str | None = None):
    with conectar() as conn:
        itens = armazem.catalogo(conn, tipo, busca)
        tot = linha(conn, "SELECT COUNT(*) AS n, COALESCE(SUM(caracteres), 0) AS c FROM biblioteca")
    with conectar() as conn:
        sem_catalogo = linha(conn, "SELECT COUNT(*) AS n FROM biblioteca WHERE tipo = 'documento' AND resumo IS NULL")["n"]
    return {"itens": itens, "total": tot["n"], "caracteres": tot["c"], "conversor": conversor.fila.estado(),
            "sem_catalogo": sem_catalogo,
            "extensoes": armazem.EXTENSOES_ACEITAS}


@router.post("/enviar")
async def enviar(arquivos: list[UploadFile] = File(...), confiabilidade: str | None = Form(None),
                 orgao: str | None = Form(None), ano: int | None = Form(None), observacao: str | None = Form(None),
                 catalogar: bool = Form(True), origem: str = Form("biblioteca")):
    """Arquivos enviados pelo aluno (página Biblioteca ou anexo de conversa): guarda, extrai localmente e
    agenda o bibliotecário para catalogar (e transcrever, se não houver texto nem conversor local)."""
    from lamina.claude import tasks
    from lamina.orquestra.maestro import maestro

    resultados = []
    for arq in arquivos[:20]:
        conteudo = await arq.read(armazem.MAX_UPLOAD + 1)
        nome = arq.filename or "arquivo"
        try:
            r = await armazem.importar_arquivo(conteudo, nome, criado_por="aluno", orgao=orgao or None, ano=ano,
                                               confiabilidade=confiabilidade or None)
        except (ErroCaptura, ValueError) as exc:
            resultados.append({"arquivo": nome, "erro": str(exc)})
            continue
        r["arquivo"] = nome
        if catalogar and not r["ja_existia"]:
            with conectar() as conn:
                titulo, instrucoes = tasks.tarefa_catalogo(armazem.obter(conn, r["id"]), observacao, origem)
                cur = conn.execute(
                    "INSERT INTO tarefas (agente, titulo, instrucoes, prioridade, criado_por, aguarda_doc) "
                    "VALUES ('bibliotecario', ?, ?, ?, 'aluno', ?)",
                    (titulo, instrucoes, 1 if origem == "biblioteca" else 2,
                     r["id"] if r.get("conversao_local") else None))
                r["tarefa_id"] = cur.lastrowid
        resultados.append(r)
    if origem == "biblioteca":  # pedido explícito do aluno: começa já o que não depende do conversor (envios pequenos)
        from lamina.orquestra.maestro import envio_pequeno

        prontas = [r for r in resultados if r.get("tarefa_id") and not r.get("conversao_local")]
        with conectar() as conn:
            pequeno = envio_pequeno(conn)
        if prontas and pequeno:
            maestro.disparar_tarefa(prontas[0]["tarefa_id"], fundo=False)
    return {"resultados": resultados}


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
    tipos = {".pdf": "application/pdf", ".html": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8",
             ".md": "text/plain; charset=utf-8", **{f".{k}": v for k, v in armazem.IMAGENS.items()}}
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


@router.post("/catalogar-pendentes")
async def catalogar_pendentes():
    """Catalogação em lote pelo Haiku (metadados, área, temas, resumo) dos documentos sem resumo."""
    from lamina.orquestra.maestro import maestro

    if not maestro.disparar_catalogo(fundo=False):
        raise HTTPException(409, f"há outro trabalho em andamento: {maestro.ocupado}")
    return {"iniciado": True}


@router.post("/{doc_id}/reconverter")
def reconverter(doc_id: str):
    if not conversor.disponivel():
        raise HTTPException(409, "conversor local não instalado (scripts/instalar_conversor.sh)")
    with conectar() as conn:
        d = _doc(conn, doc_id)
        if d["tipo"] != "documento" or d["formato"] not in ("pdf", "imagem"):
            raise HTTPException(422, "só PDFs e imagens passam pelo conversor")
        conversor.marcar_pendente(conn, doc_id)
    return {"ok": True}


@router.delete("/{doc_id}")
def remover(doc_id: str):
    with conectar() as conn:
        _doc(conn, doc_id)
        armazem.remover(conn, doc_id)
    return {"ok": True}
