"""Captura de documentos da web: download seguro e extração do texto integral.

O WebFetch do Claude Code devolve ao modelo um resumo da página, não o documento. Aqui o próprio app
baixa o arquivo (PDF, HTML ou texto), extrai o texto completo e o entrega à biblioteca, onde fica
persistente e pesquisável por todos os agentes.

Segurança: a URL vem de um agente que lê páginas da web (possível injeção de instruções). Por isso
só http(s), apenas endereços públicos (verificados a cada redirecionamento) e tamanho limitado.
"""

from __future__ import annotations

import asyncio
import html as html_mod
import ipaddress
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 80 * 1024 * 1024
TIMEOUT = httpx.Timeout(90.0, connect=20.0)
MAX_REDIRECIONAMENTOS = 6
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0 Safari/537.36 Lamina/1.0")

# Injetáveis nos testes (sem rede).
_transporte: httpx.AsyncBaseTransport | None = None
_resolver: Callable[[str], list[str]] | None = None


class ErroCaptura(Exception):
    pass


class PdfSemTexto(ErroCaptura):
    """PDF escaneado (só imagem): precisa de transcrição (o Claude lê as páginas como imagem)."""

    def __init__(self, paginas: int, titulo: str | None):
        super().__init__("PDF sem texto extraível (provavelmente escaneado como imagem)")
        self.paginas = paginas
        self.titulo = titulo


@dataclass
class Download:
    conteudo: bytes
    tipo: str
    url: str


@dataclass
class Extraido:
    titulo: str | None
    texto: str
    formato: str
    paginas: int | None = None
    links: list[dict] = field(default_factory=list)


def marca_pagina(n: int) -> str:
    return f"[[página {n}]]"


RE_PAGINA = re.compile(r"\[\[página (\d+)\]\]")


# ------------------------------------------------------------------------------------------------
# Download
# ------------------------------------------------------------------------------------------------


async def _ips(host: str) -> list[str]:
    if _resolver:
        return _resolver(host)
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [i[4][0] for i in infos]


async def validar_url(url: str) -> None:
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https"):
        raise ErroCaptura("só endereços http(s) podem ser capturados")
    if not partes.hostname:
        raise ErroCaptura("URL sem host")
    try:
        ips = await _ips(partes.hostname)
    except (socket.gaierror, OSError) as exc:
        raise ErroCaptura(f"não foi possível resolver {partes.hostname}") from exc
    if not ips:
        raise ErroCaptura(f"não foi possível resolver {partes.hostname}")
    for ip in ips:
        if not ipaddress.ip_address(ip.split("%")[0]).is_global:
            raise ErroCaptura("endereço não público bloqueado (rede local/loopback)")


async def baixar(url: str) -> Download:
    cabecalhos = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.6",
    }
    async with httpx.AsyncClient(transport=_transporte, timeout=TIMEOUT, follow_redirects=False,
                                 headers=cabecalhos) as cliente:
        atual = url
        for _ in range(MAX_REDIRECIONAMENTOS):
            await validar_url(atual)
            async with cliente.stream("GET", atual) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    atual = urljoin(atual, r.headers["location"])
                    continue
                if r.status_code >= 400:
                    raise ErroCaptura(f"HTTP {r.status_code} ao baixar {atual}")
                if int(r.headers.get("content-length") or 0) > MAX_BYTES:
                    raise ErroCaptura(f"arquivo maior que {MAX_BYTES // 2**20} MB")
                partes: list[bytes] = []
                total = 0
                async for bloco in r.aiter_bytes():
                    total += len(bloco)
                    if total > MAX_BYTES:
                        raise ErroCaptura(f"arquivo maior que {MAX_BYTES // 2**20} MB")
                    partes.append(bloco)
                tipo = r.headers.get("content-type", "").split(";")[0].strip().lower()
                return Download(b"".join(partes), tipo, atual)
        raise ErroCaptura("redirecionamentos demais")


# ------------------------------------------------------------------------------------------------
# Extração
# ------------------------------------------------------------------------------------------------


def extrair(d: Download) -> Extraido:
    c = d.conteudo
    inicio = c[:1024].lstrip().lower()
    if c[:5] == b"%PDF-" or d.tipo == "application/pdf":
        return _pdf(c)
    if d.tipo in ("text/html", "application/xhtml+xml") or inicio.startswith((b"<!doctype html", b"<html")):
        return _html(c, d.url)
    if d.tipo.startswith("text/") or d.tipo in ("application/json", "application/xml", ""):
        return Extraido(None, c.decode("utf-8", errors="replace"), "texto")
    raise ErroCaptura(f"formato não suportado: {d.tipo or 'desconhecido'}")


def _pdf(conteudo: bytes) -> Extraido:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(conteudo)
    except pdfium.PdfiumError as exc:
        raise ErroCaptura(f"PDF ilegível: {exc}") from exc
    try:
        paginas = []
        for i in range(len(pdf)):
            pagina = pdf[i]
            tp = pagina.get_textpage()
            texto = tp.get_text_bounded().replace("\r\n", "\n").replace("\r", "\n").strip()
            tp.close()
            pagina.close()
            paginas.append(f"{marca_pagina(i + 1)}\n{texto}")
        titulo = (pdf.get_metadata_dict().get("Title") or "").strip() or None
    finally:
        pdf.close()
    texto = "\n\n".join(paginas)
    util = len(RE_PAGINA.sub("", texto).split())
    if util < max(30, 8 * len(paginas)):
        raise PdfSemTexto(len(paginas), titulo)
    return Extraido(titulo, texto, "pdf", len(paginas))


_RE_LINK = re.compile(r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_RE_TAG = re.compile(r"<[^>]+>")


def _links_documentos(html: str, base: str) -> list[dict]:
    """Links para PDFs na página (portais como o gov.br costumam listar o documento em PDF)."""
    vistos, saida = set(), []
    for href, ancora in _RE_LINK.findall(html):
        h = href.lower()
        if ".pdf" not in h and "@@download" not in h:
            continue
        url = urljoin(base, html_mod.unescape(href))
        if url in vistos:
            continue
        vistos.add(url)
        texto = " ".join(html_mod.unescape(_RE_TAG.sub(" ", ancora)).split())[:140]
        saida.append({"url": url, "texto": texto})
        if len(saida) >= 25:
            break
    return saida


def _html(conteudo: bytes, url: str) -> Extraido:
    import trafilatura

    texto = trafilatura.extract(conteudo, url=url, output_format="markdown", include_tables=True,
                                include_links=False, include_comments=False, favor_recall=True)
    meta = trafilatura.extract_metadata(conteudo, default_url=url)
    bruto = conteudo.decode("utf-8", errors="replace")
    if not texto:
        corpo = re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1>", " ", bruto)
        texto = "\n".join(ln.strip() for ln in html_mod.unescape(_RE_TAG.sub("\n", corpo)).splitlines() if ln.strip())
    links = _links_documentos(bruto, url)
    if (not texto or len(texto) < 200) and not links:
        raise ErroCaptura("página sem texto aproveitável")
    return Extraido(meta.title if meta else None, texto or "", "html", None, links)
