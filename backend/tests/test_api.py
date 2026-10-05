import time

from lamina.claude.tools import ContextoCoach, desfazer, ferramentas_coach
from lamina.db import conectar, linha

Q = "unicamp-2026-ad-p1-q12"


def esperar_veredito(cliente, tid, tentativas=50):
    for _ in range(tentativas):
        t = cliente.get(f"/api/tentativas/{tid}").json()
        if t["veredito"] != "pendente":
            return t
        time.sleep(0.05)
    raise AssertionError("veredito não chegou")


def test_gabarito_so_aparece_depois_de_responder(cliente):
    q = cliente.get(f"/api/questoes/{Q}").json()
    assert q["gabarito"] is None
    assert q["imagens"][0]["url"] == "/imagens/2026-ad-p1/q12.png"
    assert cliente.get(q["imagens"][0]["url"]).status_code == 200

    r = cliente.post("/api/tentativas", json={"questao_id": Q, "resposta": "hemorragia CERTO", "confianca": "certeza"})
    corpo = r.json()
    assert corpo["gabarito"]["resposta_esperada"].startswith("hemorragia recente")
    t = esperar_veredito(cliente, corpo["tentativa"]["id"])
    assert t["veredito"] == "correto" and t["fonte_veredito"] == "llm"
    assert cliente.get(f"/api/questoes/{Q}").json()["gabarito"] is not None


def test_override_manual_do_veredito(cliente):
    tid = cliente.post("/api/tentativas", json={"questao_id": Q, "resposta": "errei", "confianca": "chute"}).json()["tentativa"]["id"]
    assert esperar_veredito(cliente, tid)["veredito"] == "incorreto"
    t = cliente.patch(f"/api/tentativas/{tid}", json={"veredito": "correto"}).json()
    assert t["veredito"] == "correto" and t["fonte_veredito"] == "manual"


def test_bloco_de_tema_e_refazer(cliente):
    tema_id = cliente.get(f"/api/questoes/{Q}").json()["tema_id"]
    b = cliente.post("/api/blocos", json={"tipo": "tema", "tema_id": tema_id}).json()
    bloco = cliente.get(f"/api/blocos/{b['id']}").json()
    assert bloco["bloco"]["tipo"] == "tema" and len(bloco["questoes"]) == b["n"]
    primeira = bloco["questoes"][0]["id"]
    tid = cliente.post("/api/tentativas", json={"questao_id": primeira, "resposta": "nada", "confianca": "certeza",
                                                "bloco_id": b["id"]}).json()["tentativa"]["id"]
    esperar_veredito(cliente, tid)
    r = cliente.post("/api/blocos", json={"tipo": "refazer", "bloco_origem_id": b["id"]}).json()
    assert r["n"] == 1


def test_simulado_esconde_gabarito_e_corrige_em_lote(cliente):
    b = cliente.post("/api/blocos", json={"tipo": "simulado"}).json()
    assert b["n"] == 50
    bloco = cliente.get(f"/api/blocos/{b['id']}").json()
    q1 = bloco["questoes"][0]["id"]
    r = cliente.post("/api/tentativas", json={"questao_id": q1, "resposta": "x", "confianca": "duvida",
                                              "bloco_id": b["id"]}).json()
    assert r["gabarito"] is None and r["julgando"] is False
    assert cliente.get(f"/api/questoes/{q1}?bloco_id={b['id']}").json()["gabarito"] is None
    assert cliente.post(f"/api/blocos/{b['id']}/finalizar").json()["julgando"] == 1
    t = esperar_veredito(cliente, r["tentativa"]["id"])
    assert t["veredito"] == "correto"


def test_flashcards_gerar_salvar_revisar(cliente):
    cartoes = cliente.post(f"/api/questoes/{Q}/flashcards/gerar", json={}).json()["cartoes"]
    assert len(cartoes) == 2
    ids = cliente.post("/api/flashcards", json={"cartoes": [{**c, "questao_id": Q} for c in cartoes]}).json()["ids"]
    vencidos = cliente.get("/api/flashcards?vencidos=true").json()["cartoes"]
    assert {c["id"] for c in vencidos} == set(ids)
    assert cliente.post(f"/api/flashcards/{ids[0]}/revisar", json={"nota": 3}).status_code == 200


def test_chat_tutor_streaming_e_fixar_explicacao(cliente):
    chat = cliente.post(f"/api/questoes/{Q}/chat").json()["chat"]
    with cliente.stream("POST", f"/api/chats/{chat['id']}/mensagens", json={"texto": "Explique"}) as r:
        corpo = "".join(r.iter_text())
    assert '"tipo": "texto"' in corpo and '"tipo": "fim"' in corpo
    dados = cliente.post(f"/api/questoes/{Q}/chat").json()
    assert [m["papel"] for m in dados["mensagens"]] == ["user", "assistant"]
    assert dados["chat"]["session_id"] == "sessao-fake"
    mid = dados["mensagens"][1]["id"]
    cliente.put(f"/api/questoes/{Q}/explicacao", json={"mensagem_id": mid})
    assert "didática" in cliente.get(f"/api/questoes/{Q}").json()["explicacao"]["explicacao_md"]


def test_painel_e_temas(cliente):
    p = cliente.get("/api/painel").json()
    assert p["totais"]["questoes_banco"] == 647
    assert len(p["prioritarios"]) == 3
    temas = cliente.get("/api/temas").json()
    assert sum(t["total"] for t in temas) == 647
    tid = temas[0]["id"]
    cliente.patch(f"/api/temas/{tid}", json={"status_manual": "dominado"})
    assert next(t for t in cliente.get("/api/temas").json() if t["id"] == tid)["status"] == "dominado"


async def test_ferramentas_do_coach_e_desfazer(ambiente):
    ctx = ContextoCoach()
    tools = {t.name: t for t in ferramentas_coach(ctx)}
    pano = await tools["panorama"].handler({})
    assert "temas_por_prioridade" in pano["content"][0]["text"]
    with conectar() as conn:
        tema = linha(conn, "SELECT id, peso_coach FROM temas LIMIT 1")
    await tools["ajustar_peso_tema"].handler({"tema_id": tema["id"], "peso": 5, "motivo": "teste"})
    await tools["criar_bloco"].handler({"nome": "B", "objetivo": "o", "questao_ids": [Q, "inexistente"]})
    await tools["publicar_missoes_do_dia"].handler({"missoes": [{"titulo": "M1"}, {"titulo": "M2"}]})
    assert len(ctx.acoes) == 3
    with conectar() as conn:
        assert linha(conn, "SELECT peso_coach FROM temas WHERE id = ?", (tema["id"],))["peso_coach"] == 2.0
        for a in ctx.acoes:
            assert desfazer(conn, a)
        assert linha(conn, "SELECT peso_coach FROM temas WHERE id = ?", (tema["id"],))["peso_coach"] == tema["peso_coach"]
        assert linha(conn, "SELECT COUNT(*) AS n FROM blocos WHERE arquivado = 0")["n"] == 0
        assert linha(conn, "SELECT COUNT(*) AS n FROM coach_insights WHERE arquivado = 0")["n"] == 0
