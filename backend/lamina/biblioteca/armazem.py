"""Biblioteca compartilhada pelos agentes: documentos integrais e notas verificadas.

Arquivos em `app_data/biblioteca/` (fora do git: documentos de sociedades têm direitos autorais):
  docs/<id>/texto.md     texto integral extraído (PDF com marcas [[página N]])
  docs/<id>/meta.json    metadados (cópia legível do registro no banco)
  docs/<id>/original.*   arquivo baixado
  notas/<id>.md          notas-síntese escritas pelos agentes, sempre com fontes
  CATALOGO.md            índice legível (regenerado a cada mudança), útil para Glob/Grep/Read

No SQLite: tabela `biblioteca` (metadados) e `biblioteca_fts` (busca em texto completo, sem acentos).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import sqlite3
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from lamina import config
from lamina.biblioteca import captura, conversor
from lamina.biblioteca.captura import RE_PAGINA, ErroCaptura
from lamina.db import conectar, linha, linhas
from lamina.importer import slug

CONFIABILIDADES = ("oficial", "sociedade", "literatura", "nota")
STATUS = ("vigente", "substituido", "em_revisao")
TAM_TRECHO = 1500
_EXT = {"pdf": "pdf", "html": "html", "texto": "txt"}

_STOP = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas", "para", "por",
         "com", "um", "uma", "uns", "umas", "que", "qual", "quais", "como", "se", "ao", "aos", "à", "às", "ou",
         "é", "ser", "são", "sobre", "entre", "pelo", "pela", "pelos", "pelas", "sem", "mais", "menos", "muito",
         "deve", "devem", "quando", "onde", "the", "of", "and", "in", "for", "to"}


def _agora() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _raiz() -> Path:
    return config.BIBLIOTECA_DIR


def caminho_texto(doc: dict) -> Path:
    if doc["tipo"] == "nota":
        return _raiz() / "notas" / f"{doc['id']}.md"
    return _raiz() / "docs" / doc["id"] / "texto.md"


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c)).lower()


def _novo_id(conn: sqlite3.Connection, titulo: str, ano: int | None) -> str:
    base = slug(titulo)[:64].strip("-") or "documento"
    if ano and str(ano) not in base:
        base = f"{base}-{ano}"
    cand, n = base, 2
    while linha(conn, "SELECT 1 AS x FROM biblioteca WHERE id = ?", (cand,)):
        cand, n = f"{base}-{n}", n + 1
    return cand


# ------------------------------------------------------------------------------------------------
# Índice
# ------------------------------------------------------------------------------------------------


def _janelas(texto: str, tamanho: int = TAM_TRECHO) -> list[str]:
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    saida, atual = [], ""
    for p in paragrafos:
        while len(p) > tamanho * 1.5:  # parágrafo gigante (PDF sem quebras): fatia
            if atual:
                saida.append(atual)
                atual = ""
            saida.append(p[:tamanho])
            p = p[tamanho:]
        if atual and len(atual) + len(p) > tamanho:
            saida.append(atual)
            atual = p
        else:
            atual = f"{atual}\n\n{p}" if atual else p
    if atual:
        saida.append(atual)
    return saida


def trechos(texto: str) -> list[tuple[str, str]]:
    """Divide o texto em trechos de ~1500 caracteres com a localização (página ou seção)."""
    partes = RE_PAGINA.split(texto)
    if len(partes) > 1:
        segmentos = [(f"p. {partes[i]}", partes[i + 1]) for i in range(1, len(partes), 2)]
    else:
        segmentos, secao, buffer = [], "início", []
        for ln in texto.splitlines():
            m = re.match(r"^#{1,4}\s+(.+)$", ln)
            if m:
                if buffer:
                    segmentos.append((secao, "\n".join(buffer)))
                secao, buffer = m.group(1).strip()[:90], [ln]
            else:
                buffer.append(ln)
        if buffer:
            segmentos.append((secao, "\n".join(buffer)))
    return [(local, j) for local, t in segmentos for j in _janelas(t) if j.strip()]


def indexar(conn: sqlite3.Connection, doc_id: str, titulo: str, texto: str) -> int:
    conn.execute("DELETE FROM biblioteca_fts WHERE doc_id = ?", (doc_id,))
    itens = trechos(texto)
    conn.executemany("INSERT INTO biblioteca_fts (doc_id, local, titulo, texto) VALUES (?, ?, ?, ?)",
                     [(doc_id, local, titulo, t) for local, t in itens])
    return len(itens)


def _termos(consulta: str) -> list[str]:
    return [t for t in re.findall(r"\w+", _sem_acento(consulta)) if len(t) > 1 and t not in _STOP][:12]


def _expr(termos: list[str], juncao: str) -> str:
    def termo(t: str) -> str:
        return f'"{t[:max(5, len(t) - 2)]}"*' if len(t) > 6 else f'"{t}"'
    return f" {juncao} ".join(termo(t) for t in termos)


def buscar(conn: sqlite3.Connection, consulta: str, limite: int = 8, confiabilidade: str | None = None,
           tipo: str | None = None, por_documento: int = 3) -> list[dict]:
    termos = _termos(consulta)
    if not termos:
        return []
    filtros, params = [], []
    if confiabilidade:
        filtros.append("AND b.confiabilidade = ?")
        params.append(confiabilidade)
    if tipo:
        filtros.append("AND b.tipo = ?")
        params.append(tipo)
    sql = f"""
        SELECT f.doc_id, f.local, snippet(biblioteca_fts, 3, '**', '**', ' … ', 28) AS trecho,
               bm25(biblioteca_fts, 0, 0, 2.0, 1.0) AS score, b.titulo, b.tipo, b.orgao, b.ano,
               b.confiabilidade, b.status, b.url
        FROM biblioteca_fts f JOIN biblioteca b ON b.id = f.doc_id
        WHERE biblioteca_fts MATCH ? {' '.join(filtros)}
        ORDER BY (b.status != 'vigente'), score LIMIT ?"""
    resultados: list[dict] = []
    for juncao in ("AND", "OR"):
        if len(termos) == 1 and juncao == "OR":
            break
        try:
            resultados = linhas(conn, sql, (_expr(termos, juncao), *params, limite * 6))
        except sqlite3.OperationalError:
            resultados = []
        if len(resultados) >= min(3, limite):
            break
    contagem: dict[str, int] = {}
    saida = []
    for r in resultados:
        contagem[r["doc_id"]] = contagem.get(r["doc_id"], 0) + 1
        if contagem[r["doc_id"]] <= por_documento:
            r["score"] = round(r["score"], 2)
            saida.append(r)
        if len(saida) >= limite:
            break
    return saida


# ------------------------------------------------------------------------------------------------
# Leitura
# ------------------------------------------------------------------------------------------------


def obter(conn: sqlite3.Connection, doc_id: str) -> dict | None:
    d = linha(conn, "SELECT * FROM biblioteca WHERE id = ?", (doc_id,))
    if d:
        d["temas"] = json.loads(d.pop("temas_json") or "[]")
        d["fontes"] = json.loads(d.pop("fontes_json") or "[]")
        d["caminho"] = str(caminho_texto(d))
    return d


def _limites_paginas(texto: str, de: int, ate: int) -> tuple[int, int] | None:
    marcas = {int(m.group(1)): m.start() for m in RE_PAGINA.finditer(texto)}
    if de not in marcas:
        return None
    fim = next((marcas[p] for p in sorted(marcas) if p > ate), len(texto))
    return marcas[de], fim


def ler(conn: sqlite3.Connection, doc_id: str, pagina: int | None = None, ate_pagina: int | None = None,
        trecho: str | None = None, inicio: int = 0, max_caracteres: int = 12_000, contar_acesso: bool = True) -> dict:
    doc = obter(conn, doc_id)
    if not doc:
        raise KeyError(doc_id)
    texto = caminho_texto(doc).read_text(encoding="utf-8")
    max_caracteres = max(500, min(int(max_caracteres or 12_000), 40_000))
    a, b = 0, None
    if pagina:
        lim = _limites_paginas(texto, int(pagina), int(ate_pagina or pagina))
        if not lim:
            raise ValueError(f"página {pagina} não existe (o documento tem {doc['paginas'] or 0} páginas)")
        a, b = lim
    elif trecho:
        pos = _sem_acento(texto).find(_sem_acento(trecho))
        if pos < 0:
            raise ValueError("trecho não encontrado; use biblioteca_buscar para localizar")
        a = max(0, pos - 1500)
    else:
        a = max(0, int(inicio or 0))
    b = min(b if b is not None else len(texto), a + max_caracteres)
    if contar_acesso:
        conn.execute("UPDATE biblioteca SET acessos = acessos + 1 WHERE id = ?", (doc_id,))
    return {
        "id": doc_id, "titulo": doc["titulo"], "orgao": doc["orgao"], "ano": doc["ano"], "url": doc["url"],
        "status": doc["status"], "inicio": a, "fim": b, "total_caracteres": len(texto), "paginas": doc["paginas"],
        "texto": texto[a:b], "continua": b < len(texto),
    }


def catalogo(conn: sqlite3.Connection, tipo: str | None = None, busca: str | None = None) -> list[dict]:
    sql = ["SELECT id, tipo, titulo, orgao, ano, categoria, confiabilidade, status, paginas, caracteres, url,",
           "temas_json, criado_por, acessos, criado_em, atualizado_em, conversao FROM biblioteca WHERE 1=1"]
    params: list = []
    if tipo:
        sql.append("AND tipo = ?")
        params.append(tipo)
    if busca:
        sql.append("AND (titulo LIKE ? OR orgao LIKE ? OR temas_json LIKE ?)")
        params += [f"%{busca}%"] * 3
    sql.append("ORDER BY (status != 'vigente'), atualizado_em DESC")
    itens = linhas(conn, " ".join(sql), params)
    for i in itens:
        i["temas"] = json.loads(i.pop("temas_json") or "[]")
    return itens


def resumo_para_prompt(conn: sqlite3.Connection, limite: int = 40) -> str:
    """Visão curta da biblioteca para o prompt de sistema dos agentes."""
    n = linha(conn, "SELECT COUNT(*) AS n, SUM(tipo = 'documento') AS d, SUM(tipo = 'nota') AS t FROM biblioteca")
    if not n or not n["n"]:
        return "A biblioteca ainda está vazia."
    itens = linhas(conn, """SELECT id, tipo, titulo, orgao, ano, status FROM biblioteca
                            ORDER BY (status != 'vigente'), acessos DESC, atualizado_em DESC LIMIT ?""", (limite,))
    linhas_txt = [f"- {i['id']} · {i['titulo'][:90]} ({i['orgao'] or '?'}, {i['ano'] or 's/d'})"
                  + (" [nota]" if i["tipo"] == "nota" else "") + (" [SUBSTITUÍDO]" if i["status"] == "substituido" else "")
                  for i in itens]
    extra = f"\n(+{n['n'] - len(itens)} itens; veja CATALOGO.md ou biblioteca_catalogo)" if n["n"] > len(itens) else ""
    return f"{n['d'] or 0} documentos e {n['t'] or 0} notas. Mais usados/recentes:\n" + "\n".join(linhas_txt) + extra


def regenerar_catalogo(conn: sqlite3.Connection) -> None:
    itens = catalogo(conn)
    cab = ["# Catálogo da biblioteca", "", "Gerado automaticamente. Texto integral em docs/<id>/texto.md; notas em notas/<id>.md.",
           "", "| id | tipo | título | órgão | ano | confiab. | status |", "|---|---|---|---|---|---|---|"]
    corpo = [f"| {i['id']} | {i['tipo']} | {i['titulo'].replace('|', '/')} | {i['orgao'] or ''} | {i['ano'] or ''} | "
             f"{i['confiabilidade']} | {i['status']} |" for i in itens]
    _raiz().mkdir(parents=True, exist_ok=True)
    (_raiz() / "CATALOGO.md").write_text("\n".join(cab + corpo) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------------------------
# Escrita
# ------------------------------------------------------------------------------------------------


def _validar_confiabilidade(c: str | None, tipo: str) -> str:
    if tipo == "nota":
        return "nota"
    c = (c or "literatura").lower()
    if c not in CONFIABILIDADES[:3]:
        raise ValueError(f"confiabilidade deve ser uma de {CONFIABILIDADES[:3]}")
    return c


def _sumario(texto: str, formato: str) -> str:
    if formato == "pdf":
        corpo = RE_PAGINA.sub("", texto)
        return " ".join(corpo.split())[:900]
    titulos = [ln.strip() for ln in texto.splitlines() if re.match(r"^#{1,4}\s", ln)]
    if titulos:
        return "\n".join(titulos[:40])
    return " ".join(texto.split())[:900]


def _gravar(conn: sqlite3.Connection, *, doc_id: str | None, conteudo: bytes, sha: str, texto: str, formato: str,
            ext: str, paginas: int | None, titulo: str, criado_por: str, orgao: str | None = None,
            ano: int | None = None, categoria: str | None = None, confiabilidade: str = "literatura",
            temas: list[str] | None = None, resumo: str | None = None, url: str | None = None,
            status: str = "vigente", status_motivo: str | None = None, meta_extra: dict | None = None) -> tuple[str, int]:
    """Grava arquivos, metadados e índice de um documento (novo ou substituindo `doc_id`)."""
    doc_id = doc_id or _novo_id(conn, titulo, ano)
    pasta = _raiz() / "docs" / doc_id
    if pasta.exists():
        shutil.rmtree(pasta)
    pasta.mkdir(parents=True)
    (pasta / "texto.md").write_text(texto, encoding="utf-8")
    (pasta / f"original.{ext}").write_bytes(conteudo)
    valores = dict(id=doc_id, tipo="documento", titulo=titulo, orgao=orgao, ano=ano, categoria=categoria,
                   confiabilidade=confiabilidade, status=status, status_motivo=status_motivo, url=url, formato=formato,
                   paginas=paginas, caracteres=len(texto), sha256=sha,
                   temas_json=json.dumps(temas or [], ensure_ascii=False), resumo=resumo, criado_por=criado_por,
                   conversao="pendente" if formato in ("pdf", "imagem") and conversor.disponivel() else None)
    conn.execute("DELETE FROM biblioteca WHERE id = ?", (doc_id,))
    conn.execute(f"INSERT INTO biblioteca ({', '.join(valores)}) VALUES ({', '.join('?' * len(valores))})",
                 tuple(valores.values()))
    n = indexar(conn, doc_id, titulo, texto)
    (pasta / "meta.json").write_text(json.dumps({**valores, **(meta_extra or {}), "guardado_em": _agora()},
                                                ensure_ascii=False, indent=2), encoding="utf-8")
    regenerar_catalogo(conn)
    return doc_id, n


async def capturar(url: str, *, criado_por: str, titulo: str | None = None, orgao: str | None = None,
                   ano: int | None = None, categoria: str | None = None, confiabilidade: str | None = None,
                   temas: list[str] | None = None, resumo: str | None = None, substituir: bool = False) -> dict:
    """Baixa, extrai, guarda e indexa um documento. Não devolve o texto (economia de tokens)."""
    conf = _validar_confiabilidade(confiabilidade, "documento")
    with conectar() as conn:
        existente = linha(conn, "SELECT * FROM biblioteca WHERE url = ? AND tipo = 'documento'", (url,))
    if existente and not substituir:
        return {"id": existente["id"], "titulo": existente["titulo"], "ja_existia": True,
                "paginas": existente["paginas"], "caracteres": existente["caracteres"]}
    download = await captura.baixar(url)
    ex = await asyncio.to_thread(captura.extrair, download)
    if ex.formato == "html" and len(ex.texto) < 600:
        return {"armazenado": False, "motivo": "página com pouco texto (provavelmente um índice); capture um dos "
                "documentos listados", "links_documentos": ex.links}
    sha = hashlib.sha256(download.conteudo).hexdigest()
    with conectar() as conn:
        dup = linha(conn, "SELECT id, titulo FROM biblioteca WHERE sha256 = ?", (sha,))
        if dup and not substituir:
            return {"id": dup["id"], "titulo": dup["titulo"], "ja_existia": True}
        titulo_final = (titulo or ex.titulo or download.url.rsplit("/", 1)[-1] or "Documento").strip()[:200]
        alvo = existente or dup
        doc_id, n = _gravar(conn, doc_id=alvo["id"] if alvo else None, conteudo=download.conteudo, sha=sha,
                            texto=ex.texto, formato=ex.formato, ext=_EXT[ex.formato], paginas=ex.paginas,
                            titulo=titulo_final, criado_por=criado_por, orgao=orgao, ano=ano, categoria=categoria,
                            confiabilidade=conf, temas=temas, resumo=resumo, url=url,
                            meta_extra={"url_final": download.url})
    saida = {"id": doc_id, "titulo": titulo_final, "formato": ex.formato, "paginas": ex.paginas,
             "caracteres": len(ex.texto), "trechos_indexados": n, "ja_existia": False,
             "inicio_ou_sumario": _sumario(ex.texto, ex.formato)}
    if ex.formato == "pdf" and conversor.disponivel():
        saida["observacao"] = ("o conversor local (GPU) vai refazer o texto em Markdown com tabelas em alguns minutos; "
                               "as páginas continuam as mesmas")
    if ex.links:
        saida["links_documentos"] = ex.links[:15]
    return saida


# ------------------------------------------------------------------------------------------------
# Arquivos enviados pelo aluno (upload na Biblioteca ou anexo nas conversas)
# ------------------------------------------------------------------------------------------------

IMAGENS = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
TEXTOS = {"txt", "md", "markdown"}
HTMLS = {"html", "htm"}
MAX_UPLOAD = 250 * 1024 * 1024  # apostilas inteiras passam de 80 MB (limite da captura pela web)
EXTENSOES_ACEITAS = sorted({"pdf", *IMAGENS, *TEXTOS, *HTMLS})
AGUARDANDO_TRANSCRICAO = "aguardando transcrição (sem texto extraível: PDF escaneado ou imagem)"


def _titulo_do_arquivo(nome: str) -> str:
    base = Path(nome).stem
    return re.sub(r"[_\-]+", " ", base).strip().capitalize()[:200] or "Documento enviado"


async def importar_arquivo(conteudo: bytes, nome: str, *, criado_por: str = "aluno", titulo: str | None = None,
                           orgao: str | None = None, ano: int | None = None, categoria: str | None = None,
                           confiabilidade: str | None = None, temas: list[str] | None = None) -> dict:
    """Guarda um arquivo enviado. A extração é local (sem tokens); PDFs escaneados e imagens ficam
    'em revisão' até um agente transcrever (biblioteca_anexar_texto)."""
    if len(conteudo) > MAX_UPLOAD:
        raise ErroCaptura(f"arquivo maior que {MAX_UPLOAD // 2**20} MB")
    ext = Path(nome).suffix.lower().lstrip(".")
    if conteudo[:5] == b"%PDF-":
        ext = "pdf"
    if ext not in EXTENSOES_ACEITAS:
        raise ErroCaptura(f"formato não suportado ({ext or 'sem extensão'}); aceitos: {', '.join(EXTENSOES_ACEITAS)}")
    conf = _validar_confiabilidade(confiabilidade, "documento")
    sha = hashlib.sha256(conteudo).hexdigest()
    with conectar() as conn:
        dup = linha(conn, "SELECT id, titulo, status FROM biblioteca WHERE sha256 = ?", (sha,))
    if dup:
        return {"id": dup["id"], "titulo": dup["titulo"], "ja_existia": True,
                "precisa_transcricao": dup["status"] == "em_revisao"}

    texto, formato, paginas, titulo_ex, transcrever = "", "texto", None, None, False
    if ext == "pdf":
        try:
            ex = await asyncio.to_thread(captura.extrair, captura.Download(conteudo, "application/pdf", nome))
            texto, formato, paginas, titulo_ex = ex.texto, "pdf", ex.paginas, ex.titulo
        except captura.PdfSemTexto as exc:
            formato, paginas, titulo_ex, transcrever = "pdf", exc.paginas, exc.titulo, True
    elif ext in IMAGENS:
        formato, paginas, transcrever = "imagem", 1, True
    elif ext in HTMLS:
        ex = await asyncio.to_thread(captura.extrair, captura.Download(conteudo, "text/html", f"arquivo:{nome}"))
        texto, formato, titulo_ex = ex.texto, "html", ex.titulo
    else:
        texto, formato = conteudo.decode("utf-8", errors="replace"), "texto"
    titulo_final = (titulo or titulo_ex or _titulo_do_arquivo(nome)).strip()[:200]
    with conectar() as conn:
        doc_id, n = _gravar(conn, doc_id=None, conteudo=conteudo, sha=sha, texto=texto, formato=formato, ext=ext,
                            paginas=paginas, titulo=titulo_final, criado_por=criado_por, orgao=orgao, ano=ano,
                            categoria=categoria, confiabilidade=conf, temas=temas,
                            status="em_revisao" if transcrever else "vigente",
                            status_motivo=AGUARDANDO_TRANSCRICAO if transcrever else None,
                            meta_extra={"nome_arquivo": nome})
    return {"id": doc_id, "titulo": titulo_final, "formato": formato, "paginas": paginas, "caracteres": len(texto),
            "trechos_indexados": n, "ja_existia": False, "precisa_transcricao": transcrever,
            "conversao_local": formato in ("pdf", "imagem") and conversor.disponivel(),
            "caminho_original": str(_raiz() / "docs" / doc_id / f"original.{ext}")}


def anexar_texto(conn: sqlite3.Connection, doc_id: str, texto: str, concluido: bool = False) -> dict:
    """Acrescenta texto transcrito (Markdown, com marcas [[página N]]) a um documento e reindexa."""
    doc = obter(conn, doc_id)
    if not doc or doc["tipo"] != "documento":
        raise KeyError(doc_id)
    caminho = caminho_texto(doc)
    atual = caminho.read_text(encoding="utf-8") if caminho.exists() else ""
    novo = (atual.rstrip() + "\n\n" + texto.strip()).strip() + "\n"
    caminho.write_text(novo, encoding="utf-8")
    conn.execute("UPDATE biblioteca SET caracteres = ?, atualizado_em = ? WHERE id = ?", (len(novo), _agora(), doc_id))
    if concluido:
        conn.execute("UPDATE biblioteca SET status = 'vigente', status_motivo = NULL WHERE id = ? "
                     "AND status_motivo = ?", (doc_id, AGUARDANDO_TRANSCRICAO))
    n = indexar(conn, doc_id, doc["titulo"], novo)
    regenerar_catalogo(conn)
    return {"id": doc_id, "caracteres": len(novo), "trechos_indexados": n, "concluido": concluido}


def salvar_nota(conn: sqlite3.Connection, *, titulo: str, conteudo: str, fontes: list[str], criado_por: str,
                temas: list[str] | None = None, resumo: str | None = None, nota_id: str | None = None) -> dict:
    fontes = [f.strip() for f in fontes if f and f.strip()]
    if not fontes:
        raise ValueError("toda nota precisa de pelo menos uma fonte (id de documento da biblioteca ou URL)")
    invalidas = [f for f in fontes if not f.startswith("http") and not linha(
        conn, "SELECT 1 AS x FROM biblioteca WHERE id = ?", (f,))]
    if invalidas:
        raise ValueError(f"fontes inexistentes na biblioteca: {invalidas}")
    if nota_id:
        atual = linha(conn, "SELECT * FROM biblioteca WHERE id = ? AND tipo = 'nota'", (nota_id,))
        if not atual:
            raise KeyError(nota_id)
        conn.execute("""UPDATE biblioteca SET titulo = ?, fontes_json = ?, temas_json = ?, resumo = ?,
                          caracteres = ?, status = 'vigente', atualizado_em = ? WHERE id = ?""",
                     (titulo, json.dumps(fontes, ensure_ascii=False), json.dumps(temas or [], ensure_ascii=False),
                      resumo, len(conteudo), _agora(), nota_id))
    else:
        nota_id = _novo_id(conn, f"nota-{titulo}", None)
        conn.execute("""INSERT INTO biblioteca (id, tipo, titulo, confiabilidade, formato, caracteres, fontes_json,
                          temas_json, resumo, criado_por) VALUES (?, 'nota', ?, 'nota', 'markdown', ?, ?, ?, ?, ?)""",
                     (nota_id, titulo, len(conteudo), json.dumps(fontes, ensure_ascii=False),
                      json.dumps(temas or [], ensure_ascii=False), resumo, criado_por))
    caminho = _raiz() / "notas" / f"{nota_id}.md"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    corpo = conteudo.strip()
    cab = (f"<!-- nota da biblioteca · autor: {criado_por} · atualizada em {_agora()[:10]} · "
           f"fontes: {', '.join(fontes)} -->\n" + ("" if corpo.startswith("# ") else f"# {titulo}\n\n"))
    caminho.write_text(cab + corpo + "\n", encoding="utf-8")
    indexar(conn, nota_id, titulo, conteudo)
    regenerar_catalogo(conn)
    return {"id": nota_id, "caminho": str(caminho)}


def marcar(conn: sqlite3.Connection, doc_id: str, status: str, motivo: str | None = None) -> None:
    if status not in STATUS:
        raise ValueError(f"status deve ser um de {STATUS}")
    cur = conn.execute("UPDATE biblioteca SET status = ?, status_motivo = ?, atualizado_em = ? WHERE id = ?",
                       (status, motivo, _agora(), doc_id))
    if not cur.rowcount:
        raise KeyError(doc_id)
    regenerar_catalogo(conn)


CAMPOS_EDITAVEIS = ("titulo", "orgao", "ano", "categoria", "confiabilidade", "resumo", "temas")


def editar(conn: sqlite3.Connection, doc_id: str, campos: dict) -> None:
    doc = obter(conn, doc_id)
    if not doc:
        raise KeyError(doc_id)
    for k, v in campos.items():
        if k not in CAMPOS_EDITAVEIS:
            continue
        if k == "confiabilidade":
            v = _validar_confiabilidade(v, doc["tipo"])
        col, val = ("temas_json", json.dumps(v or [], ensure_ascii=False)) if k == "temas" else (k, v)
        conn.execute(f"UPDATE biblioteca SET {col} = ?, atualizado_em = ? WHERE id = ?", (val, _agora(), doc_id))
    regenerar_catalogo(conn)


def remover(conn: sqlite3.Connection, doc_id: str) -> None:
    doc = obter(conn, doc_id)
    if not doc:
        raise KeyError(doc_id)
    conn.execute("DELETE FROM biblioteca_fts WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM biblioteca WHERE id = ?", (doc_id,))
    if doc["tipo"] == "nota":
        caminho_texto(doc).unlink(missing_ok=True)
    else:
        shutil.rmtree(_raiz() / "docs" / doc_id, ignore_errors=True)
    regenerar_catalogo(conn)


__all__ = ["ErroCaptura", "buscar", "capturar", "catalogo", "editar", "ler", "marcar", "obter", "remover",
           "resumo_para_prompt", "salvar_nota"]
