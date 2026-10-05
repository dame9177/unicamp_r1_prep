import pytest

from lamina.claude import terminal
from lamina.db import conectar, linha
from tests.test_api import Q, esperar_veredito


def test_juiz_em_dois_estagios_prioriza_recomendacao_atual(cliente, fake_runner):
    r = cliente.post("/api/tentativas", json={"questao_id": Q, "resposta": "ATUALIZAR rifampicina", "confianca": "certeza"})
    t = esperar_veredito(cliente, r.json()["tentativa"]["id"])
    assert t["veredito"] == "correto"
    assert "rifampicina" in t["adendo"]
    refs = [p.ref for p in fake_runner.pedidos if p.papel == "juiz"]
    assert refs[-1].endswith(":atualizacao")
    estagio2 = fake_runner.pedidos[-1]
    assert "WebSearch" in estagio2.ferramentas and any("terminal" in n for n in estagio2.permitidas)


def test_tutor_e_coach_recebem_kit_de_ferramentas(cliente, fake_runner):
    chat = cliente.post(f"/api/questoes/{Q}/chat").json()["chat"]
    with cliente.stream("POST", f"/api/chats/{chat['id']}/mensagens", json={"texto": "oi"}) as resp:
        "".join(resp.iter_text())
    tutor = next(p for p in fake_runner.pedidos if p.papel == "tutor")
    assert {"WebSearch", "WebFetch", "Read"} <= set(tutor.ferramentas)
    assert {"mcp__lamina__terminal", "mcp__lamina__buscar_questoes", "mcp__lamina__criar_flashcards"} <= set(tutor.permitidas)
    assert "mcp__lamina__publicar_insight" not in tutor.permitidas


@pytest.mark.skipif(not terminal.disponivel(), reason="bwrap ausente")
async def test_terminal_isolado(ambiente):
    saida = await terminal.executar("python3 -c 'print(6*7)'; ls /dados; touch /dados/banco_questoes/x; ls /home; "
                                    "python3 -c \"import sqlite3;print(sqlite3.connect('/dados/lamina.db').execute('select count(*) from questoes').fetchone()[0])\"")
    assert "42" in saida and "banco_questoes" in saida and "lamina.db" in saida
    assert "Read-only file system" in saida
    assert "650" in saida
    rede = await terminal.executar("python3 -c 'import urllib.request;urllib.request.urlopen(\"https://example.com\", timeout=3)'")
    assert "Error" in rede or "error" in rede
    with conectar() as conn:
        assert linha(conn, "SELECT COUNT(*) AS n FROM questoes")["n"] == 650
