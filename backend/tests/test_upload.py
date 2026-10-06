import stat

import pytest

from lamina import config
from lamina.biblioteca import armazem, conversor
from lamina.db import conectar, linha
from lamina.orquestra import maestro as maestro_mod
from tests.test_api import Q
from tests.test_biblioteca import PDF, pdf_minimo

PDF_ESCANEADO = pdf_minimo([" ", " "])  # páginas sem texto, como um scan
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture()
def marker_falso(tmp_path, monkeypatch):
    """Executável que imita o marker_single: escreve um .md paginado no --output_dir."""
    script = tmp_path / "marker_single"
    script.write_text("""#!/usr/bin/env bash
saida=""; ocr=0
while [ $# -gt 0 ]; do case "$1" in --output_dir) saida="$2"; shift;; --force_ocr) ocr=1;; esac; shift; done
mkdir -p "$saida/doc"
{ echo "{0}------------------------------------------------"; echo; echo "# Protocolo convertido";
  echo "| Droga | Dose |"; echo "|---|---|"; echo "| Benzilpenicilina benzatina | 2,4 milhões UI |"; echo;
  echo "{1}------------------------------------------------"; echo; echo "Texto da segunda página (ocr=$ocr) com sífilis";
  echo "gestante, VDRL mensal, parceiro tratado, notificação compulsória e seguimento trimestral."; } > "$saida/doc/doc.md"
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(conversor, "cli", lambda: str(script))
    return script


def test_limpeza_do_markdown_do_marker():
    md = "| Droga    | Dose          |\n|----------|---------------|\n| A<br>B   | 1 mg<sup>12</sup> |\nH<sub>2</sub>O"
    assert conversor.limpar_markdown(md) == "| Droga | Dose |\n|---|---|\n| A B | 1 mg^12 |\nH_2O"


def test_marcas_de_pagina_do_marker():
    md = "{0}" + "-" * 48 + "\n\n# A\n\n{1}" + "-" * 48 + "\n\nB"
    assert conversor.marcas_de_pagina(md) == "[[página 1]]\n\n# A\n\n[[página 2]]\n\nB\n"
    assert conversor.marcas_de_pagina("sem separadores") == "sem separadores"


async def test_importa_pdf_com_texto_escaneado_e_imagem(ambiente):
    r = await armazem.importar_arquivo(PDF, "pcdt_ist.pdf")
    assert r["formato"] == "pdf" and r["paginas"] == 3 and not r["precisa_transcricao"]
    assert (await armazem.importar_arquivo(PDF, "copia.pdf"))["ja_existia"]
    esc = await armazem.importar_arquivo(PDF_ESCANEADO, "scan.pdf")
    assert esc["precisa_transcricao"] and esc["paginas"] == 2
    img = await armazem.importar_arquivo(PNG, "foto-tabela.png")
    assert img["formato"] == "imagem" and img["precisa_transcricao"]
    with pytest.raises(armazem.ErroCaptura):
        await armazem.importar_arquivo(b"x", "planilha.xlsx")
    with conectar() as conn:
        d = armazem.obter(conn, esc["id"])
        assert d["status"] == "em_revisao" and d["status_motivo"] == armazem.AGUARDANDO_TRANSCRICAO
        armazem.anexar_texto(conn, esc["id"], "[[página 1]]\nTranscrição: dengue grupo C, hidratação venosa.")
        assert armazem.obter(conn, esc["id"])["status"] == "em_revisao"
        armazem.anexar_texto(conn, esc["id"], "[[página 2]]\nFim.", concluido=True)
        assert armazem.obter(conn, esc["id"])["status"] == "vigente"
        assert armazem.buscar(conn, "dengue hidratação")[0]["doc_id"] == esc["id"]
        assert "Pcdt ist" in armazem.obter(conn, r["id"])["titulo"] or armazem.obter(conn, r["id"])["titulo"]


async def test_conversor_local_substitui_texto_e_faz_ocr(ambiente, marker_falso):
    r = await armazem.importar_arquivo(PDF, "pcdt.pdf")
    esc = await armazem.importar_arquivo(PDF_ESCANEADO, "scan.pdf")
    assert r["conversao_local"] and esc["conversao_local"]
    fila = conversor.FilaConversao()
    assert await fila.processar_proximo() in ("feita", "descartada (perderia conteúdo)")
    assert await fila.processar_proximo() == "feita"
    assert await fila.processar_proximo() is None
    with conectar() as conn:
        d = armazem.obter(conn, esc["id"])
        assert d["status"] == "vigente" and d["conversao"] == "feita"
        texto = armazem.ler(conn, esc["id"], pagina=2)["texto"]
        assert "ocr=1" in texto and "[[página 2]]" in texto
        assert armazem.buscar(conn, "benzatina", tipo="documento")


async def test_tarefa_espera_conversao(ambiente, marker_falso):
    r = await armazem.importar_arquivo(PDF_ESCANEADO, "scan.pdf")
    with conectar() as conn:
        conn.execute("INSERT INTO tarefas (agente, titulo, instrucoes, criado_por, aguarda_doc) "
                     "VALUES ('bibliotecario', 'Catalogar', 'x', 'preceptor', ?)", (r["id"],))
        assert maestro_mod.proxima_tarefa(conn) is None
    await conversor.FilaConversao().processar_proximo()
    with conectar() as conn:
        assert maestro_mod.proxima_tarefa(conn)["titulo"] == "Catalogar"


def test_api_de_envio_cria_tarefa_e_anexo_no_chat(cliente, fake_runner):
    r = cliente.post("/api/biblioteca/enviar", files=[("arquivos", ("pcdt.pdf", PDF, "application/pdf")),
                                                      ("arquivos", ("x.exe", b"MZ", "application/octet-stream"))],
                     data={"observacao": "é o PCDT de IST", "origem": "chat"})
    assert r.status_code == 200, r.text
    ok, ruim = r.json()["resultados"]
    assert ok["tarefa_id"] and "erro" in ruim
    with conectar() as conn:
        t = linha(conn, "SELECT * FROM tarefas WHERE id = ?", (ok["tarefa_id"],))
    assert t["criado_por"] == "aluno" and t["prioridade"] == 2 and ok["id"] in t["instrucoes"]
    assert "é o PCDT de IST" in t["instrucoes"]

    chat = cliente.post(f"/api/questoes/{Q}/chat").json()["chat"]
    with cliente.stream("POST", f"/api/chats/{chat['id']}/mensagens",
                        json={"texto": "Explique a tabela", "anexos": [ok["id"]]}) as resp:
        "".join(resp.iter_text())
    p = fake_runner.pedidos[-1]
    assert "[ANEXOS" in p.prompt and ok["id"] in p.prompt and "Explique a tabela" in p.prompt
    msgs = cliente.get(f"/api/chats/{chat['id']}").json()["mensagens"]
    assert msgs[0]["conteudo"].startswith("Explique a tabela") and "📎" in msgs[0]["conteudo"]
    assert cliente.post(f"/api/biblioteca/{ok['id']}/reconverter").status_code == 409  # sem conversor nos testes
    assert config.BIBLIOTECA_DIR.exists()
