import httpx
import pytest

from lamina import config
from lamina.biblioteca import armazem, captura
from lamina.biblioteca.captura import Download, ErroCaptura
from lamina.db import conectar, linha

PALAVRAS = ("conduta tratamento primeira linha penicilina benzatina gestante sifilis dose semanal "
            "acompanhamento VDRL mensal parceiro tratado notificacao compulsoria").split()


def pdf_minimo(paginas: list[str]) -> bytes:
    """PDF de verdade (fonte Helvetica), com texto extraível, montado à mão."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * i} 0 R' for i in range(len(paginas)))}] "
            f"/Count {len(paginas)} >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, texto in enumerate(paginas):
        linhas = [texto[k:k + 80] for k in range(0, len(texto), 80)]
        corpo = " ".join(f"({ln}) Tj 0 -14 Td" for ln in linhas)
        stream = f"BT /F1 11 Tf 50 750 Td {corpo} ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * i} 0 R "
                    "/Resources << /Font << /F1 3 0 R >> >> >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    saida, offsets = b"%PDF-1.4\n", []
    for k, o in enumerate(objs, 1):
        offsets.append(len(saida))
        saida += f"{k} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(saida)
    saida += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    saida += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    saida += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return saida


PAG1 = "Protocolo Clinico de IST. " + " ".join(PALAVRAS) + " introducao geral do documento oficial."
PAG2 = "Sifilis na gestacao: tratar com benzilpenicilina benzatina 2,4 milhoes UI. " + " ".join(PALAVRAS)
PAG3 = "Hepatites virais e HIV: testagem rapida no pre-natal. " + " ".join(PALAVRAS)
PDF = pdf_minimo([PAG1, PAG2, PAG3])

HTML = """<!doctype html><html><head><title>Calendário Nacional de Vacinação</title></head><body>
<nav>menu do portal</nav><article><h1>Calendário Nacional de Vacinação</h1>
<h2>Criança</h2><p>""" + ("A vacina BCG é aplicada ao nascer, em dose única, por via intradérmica. " * 8) + """</p>
<h2>Gestante</h2><p>""" + ("A dTpa é recomendada a partir da 20ª semana de gestação em cada gestação. " * 8) + """</p>
<p><a href="/saude/calendario-2026.pdf">Baixar o calendário em PDF</a></p></article></body></html>"""

INDICE = """<!doctype html><html><head><title>Publicações</title></head><body><p>Lista de publicações.</p>
<a href="https://www.gov.br/saude/pcdt-ist.pdf">PCDT IST 2022</a></body></html>"""


def _servidor(request: httpx.Request) -> httpx.Response:
    rotas = {
        "/saude/pcdt-ist.pdf": (200, "application/pdf", PDF),
        "/saude/pcdt-ist-copia.pdf": (200, "application/pdf", PDF),
        "/saude/calendario": (200, "text/html; charset=utf-8", HTML.encode()),
        "/saude/publicacoes": (200, "text/html", INDICE.encode()),
        "/saude/imagem.png": (200, "image/png", b"\x89PNG...."),
    }
    if request.url.path == "/saude/redirecionar":
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8765/api/saude"})
    if request.url.path not in rotas:
        return httpx.Response(404)
    status, tipo, corpo = rotas[request.url.path]
    return httpx.Response(status, headers={"content-type": tipo}, content=corpo)


@pytest.fixture()
def web(monkeypatch):
    monkeypatch.setattr(captura, "_transporte", httpx.MockTransport(_servidor))
    monkeypatch.setattr(captura, "_resolver", lambda host: [host] if host[0].isdigit() else ["93.184.216.34"])


async def test_validacao_de_url_bloqueia_rede_local():
    for url in ("file:///etc/passwd", "http://localhost:8765/api/saude", "http://127.0.0.1/", "ftp://x.org/a"):
        with pytest.raises(ErroCaptura):
            await captura.validar_url(url)


def test_extrai_pdf_por_pagina_e_html_em_markdown():
    ex = captura.extrair(Download(PDF, "application/pdf", "https://x/doc.pdf"))
    assert ex.formato == "pdf" and ex.paginas == 3
    assert "[[página 2]]" in ex.texto and "benzatina" in ex.texto
    ex = captura.extrair(Download(HTML.encode(), "text/html", "https://www.gov.br/saude/calendario"))
    assert ex.formato == "html" and "BCG" in ex.texto and "menu do portal" not in ex.texto
    assert ex.links[0]["url"] == "https://www.gov.br/saude/calendario-2026.pdf"
    with pytest.raises(ErroCaptura):
        captura.extrair(Download(b"\x89PNG", "image/png", "https://x/a.png"))


async def test_captura_indexa_le_e_evita_duplicatas(ambiente, web):
    r = await armazem.capturar("https://www.gov.br/saude/pcdt-ist.pdf", criado_por="bibliotecario",
                               titulo="PCDT IST", orgao="Ministério da Saúde", ano=2022, confiabilidade="oficial",
                               temas=["go-pre-natal"])
    assert r["paginas"] == 3 and not r["ja_existia"] and r["id"] == "pcdt-ist-2022"
    pasta = config.BIBLIOTECA_DIR / "docs" / r["id"]
    assert (pasta / "texto.md").exists() and (pasta / "original.pdf").read_bytes() == PDF
    assert "pcdt-ist-2022" in (config.BIBLIOTECA_DIR / "CATALOGO.md").read_text()

    with conectar() as conn:
        achados = armazem.buscar(conn, "sífilis gestação benzatina")
        assert achados and achados[0]["doc_id"] == "pcdt-ist-2022" and achados[0]["local"] == "p. 2"
        pag = armazem.ler(conn, "pcdt-ist-2022", pagina=2)
        assert "benzilpenicilina" in pag["texto"] and "Hepatites" not in pag["texto"]
        assert "Hepatites" in armazem.ler(conn, "pcdt-ist-2022", trecho="testagem rápida")["texto"]
        with pytest.raises(ValueError):
            armazem.ler(conn, "pcdt-ist-2022", pagina=9)
        assert linha(conn, "SELECT acessos FROM biblioteca WHERE id = 'pcdt-ist-2022'")["acessos"] == 2

    de_novo = await armazem.capturar("https://www.gov.br/saude/pcdt-ist.pdf", criado_por="tutor", titulo="x",
                                     orgao="MS", confiabilidade="oficial")
    assert de_novo["ja_existia"]
    copia = await armazem.capturar("https://www.gov.br/saude/pcdt-ist-copia.pdf", criado_por="tutor", titulo="y",
                                   orgao="MS", confiabilidade="oficial")
    assert copia["ja_existia"] and copia["id"] == "pcdt-ist-2022"


async def test_captura_html_paginas_indice_e_bloqueios(ambiente, web):
    r = await armazem.capturar("https://www.gov.br/saude/calendario", criado_por="tutor", titulo="Calendário PNI",
                               orgao="Ministério da Saúde", ano=2026, confiabilidade="oficial")
    assert r["formato"] == "html" and r["links_documentos"][0]["url"].endswith("calendario-2026.pdf")
    with conectar() as conn:
        assert armazem.buscar(conn, "dTpa gestante")[0]["local"] == "Gestante"
    indice = await armazem.capturar("https://www.gov.br/saude/publicacoes", criado_por="tutor", titulo="i",
                                    orgao="MS", confiabilidade="oficial")
    assert indice["armazenado"] is False and indice["links_documentos"][0]["texto"] == "PCDT IST 2022"
    with pytest.raises(ErroCaptura):
        await armazem.capturar("https://www.gov.br/saude/redirecionar", criado_por="tutor", titulo="r",
                               orgao="MS", confiabilidade="oficial")
    with pytest.raises(ErroCaptura):
        await armazem.capturar("https://www.gov.br/saude/imagem.png", criado_por="tutor", titulo="r",
                               orgao="MS", confiabilidade="oficial")


async def test_notas_exigem_fontes_e_entram_na_busca(ambiente, web):
    await armazem.capturar("https://www.gov.br/saude/pcdt-ist.pdf", criado_por="bibliotecario", titulo="PCDT IST",
                           orgao="Ministério da Saúde", ano=2022, confiabilidade="oficial")
    with conectar() as conn:
        with pytest.raises(ValueError):
            armazem.salvar_nota(conn, titulo="Sífilis", conteudo="x", fontes=[], criado_por="tutor")
        with pytest.raises(ValueError):
            armazem.salvar_nota(conn, titulo="Sífilis", conteudo="x", fontes=["nao-existe"], criado_por="tutor")
        n = armazem.salvar_nota(conn, titulo="Sífilis na gestação", criado_por="tutor",
                                conteudo="Tratar com **penicilina benzatina** [pcdt-ist-2022, p. 2].",
                                fontes=["pcdt-ist-2022"])
        achado = armazem.buscar(conn, "penicilina", tipo="nota")
        assert achado[0]["doc_id"] == n["id"]
        armazem.salvar_nota(conn, titulo="Sífilis na gestação", conteudo="Atualizada: VDRL mensal.",
                            fontes=["pcdt-ist-2022"], criado_por="tutor", nota_id=n["id"])
        assert "VDRL mensal" in armazem.ler(conn, n["id"])["texto"]
        armazem.marcar(conn, "pcdt-ist-2022", "substituido", "nova edição")
        assert armazem.obter(conn, "pcdt-ist-2022")["status"] == "substituido"
        assert "PCDT IST" in armazem.resumo_para_prompt(conn)
        armazem.remover(conn, "pcdt-ist-2022")
        assert not (config.BIBLIOTECA_DIR / "docs" / "pcdt-ist-2022").exists()
        assert not armazem.buscar(conn, "benzilpenicilina", tipo="documento")


def test_api_da_biblioteca(cliente, web):
    r = cliente.post("/api/biblioteca/capturar", json={"url": "https://www.gov.br/saude/pcdt-ist.pdf",
                                                       "titulo": "PCDT IST", "orgao": "MS", "ano": 2022})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    assert cliente.get("/api/biblioteca").json()["total"] == 1
    assert cliente.get("/api/biblioteca/buscar", params={"q": "benzatina"}).json()[0]["doc_id"] == doc_id
    assert "benzilpenicilina" in cliente.get(f"/api/biblioteca/{doc_id}/texto", params={"pagina": 2}).json()["texto"]
    orig = cliente.get(f"/api/biblioteca/{doc_id}/original")
    assert orig.headers["content-type"] == "application/pdf" and orig.content == PDF
    assert cliente.patch(f"/api/biblioteca/{doc_id}", json={"status": "em_revisao", "ano": 2023}).json()["ano"] == 2023
    assert cliente.post("/api/biblioteca/capturar", json={"url": "http://localhost:8765/"}).status_code == 422
    assert cliente.delete(f"/api/biblioteca/{doc_id}").json()["ok"]
    assert cliente.get(f"/api/biblioteca/{doc_id}").status_code == 404
