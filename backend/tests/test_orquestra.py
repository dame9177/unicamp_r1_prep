import time
from datetime import datetime

from lamina import agentes, ajustes, config
from lamina.claude import runner as runner_mod
from lamina.claude import tasks
from lamina.claude.tools import Contexto, desfazer, todas_ferramentas
from lamina.db import conectar, linha, salvar_ajuste
from lamina.orquestra import avisos, maestro as maestro_mod, sentinela
from tests.test_api import Q


def _ferramentas(papel="preceptor"):
    ctx = Contexto(origem=papel)
    return ctx, {t.name: t for t in todas_ferramentas(ctx)}


def test_kit_da_ao_agente_caderno_proprio_e_biblioteca(ambiente):
    k = tasks.kit("tutor")
    caderno = config.AGENTES_DIR / "tutor"
    assert k["cwd"] == str(caderno) and (caderno / "MEMORIA.md").exists()
    assert {"Write", "Edit", "Grep", "Glob", "Read", "WebSearch", "WebFetch"} <= set(k["ferramentas"])
    assert f"Edit(/{caderno}/**)" in k["permitidas"] and f"Read(/{config.BIBLIOTECA_DIR}/**)" in k["permitidas"]
    assert not any(p.startswith("Edit(") and "biblioteca" in p for p in k["permitidas"])
    nomes = set(k["permitidas"])
    assert {"mcp__lamina__biblioteca_capturar", "mcp__lamina__historico_conversas"} <= nomes
    assert "mcp__lamina__agenda_planejar" not in nomes
    assert "mcp__lamina__agenda_planejar" in tasks.kit("preceptor")["permitidas"]
    assert "mcp__lamina__biblioteca_capturar" not in tasks.kit("flashcards")["permitidas"]
    assert tasks.kit("juiz")["cwd"].endswith("agentes/juiz")

    (caderno / "MEMORIA.md").write_text("# Memória\n- aluno confunde sífilis latente", encoding="utf-8")
    s = tasks.sistema("tutor", "tutor")
    assert "aluno confunde sífilis latente" in s and "biblioteca ainda está vazia" in s and str(caderno) in s
    assert "MEMORIA" not in tasks.sistema("juiz_atualizado", "juiz")


def test_cadernos_bloqueiam_caminhos_fora(ambiente, cliente):
    agentes.workspace("tutor")
    (config.AGENTES_DIR / "tutor" / "temas").mkdir()
    (config.AGENTES_DIR / "tutor" / "temas" / "sifilis.md").write_text("pontos-chave", encoding="utf-8")
    lista = cliente.get("/api/agentes").json()
    assert next(a for a in lista if a["id"] == "tutor")["arquivos"] == 2
    assert {a["caminho"] for a in cliente.get("/api/agentes/tutor/arquivos").json()} == {"MEMORIA.md", "temas/sifilis.md"}
    assert cliente.get("/api/agentes/tutor/arquivo", params={"caminho": "temas/sifilis.md"}).json()["conteudo"] == "pontos-chave"
    assert cliente.get("/api/agentes/tutor/arquivo", params={"caminho": "../../lamina.db"}).status_code == 404


async def test_ferramentas_de_orquestracao_sao_reversiveis(ambiente):
    ctx, t = _ferramentas()
    hoje = datetime.now().date().isoformat()
    with conectar() as conn:
        conn.execute("INSERT INTO agenda (dia, titulo, origem) VALUES (?, 'do aluno', 'aluno')", (hoje,))
    await t["agenda_planejar"].handler({"dias": [{"dia": hoje, "itens": [{"titulo": "Bloco de sífilis", "tipo": "estudo"}]}]})
    await t["agenda_planejar"].handler({"dias": [{"dia": hoje, "itens": [{"titulo": "Simulado", "tipo": "simulado"},
                                                                         {"titulo": "Flashcards", "tipo": "flashcards"}]}]})
    await t["aviso_agendar"].handler({"titulo": "Estude GO", "texto": "agora", "quando": f"{hoje}T23:59"})
    await t["tarefa_delegar"].handler({"agente": "bibliotecario", "titulo": "PCDT IST", "instrucoes": "capturar"})
    with conectar() as conn:
        titulos = [r["titulo"] for r in conn.execute("SELECT titulo FROM agenda WHERE dia = ? ORDER BY id", (hoje,))]
        assert titulos == ["do aluno", "Simulado", "Flashcards"]
        for a in reversed(ctx.acoes):
            assert desfazer(conn, a)
        assert [r["titulo"] for r in conn.execute("SELECT titulo FROM agenda")] == ["do aluno"]
        assert linha(conn, "SELECT status FROM avisos")["status"] == "descartado"
        assert linha(conn, "SELECT status FROM tarefas")["status"] == "cancelada"
    sinais = await t["sinais"].handler({})
    assert "segundo_plano" in sinais["content"][0]["text"]


def test_orcamento_e_janela_controlam_o_segundo_plano(ambiente):
    with conectar() as conn:
        assert sentinela.pode_rodar_fundo(conn) == (True, "ok")
        conn.execute("INSERT INTO llm_jobs (papel, fundo, input_tokens) VALUES ('preceptor', 1, 500000)")
        ok, motivo = sentinela.pode_rodar_fundo(conn)
        assert not ok and "orçamento" in motivo
        conn.execute("UPDATE llm_jobs SET fundo = 0")
        assert sentinela.pode_rodar_fundo(conn)[0]
        conn.execute("INSERT INTO limite_uso (id, status, utilizacao, reseta_em) VALUES (1, 'allowed', 0.85, ?)",
                     (int(time.time()) + 3600,))
        assert not sentinela.pode_rodar_fundo(conn)[0]
        conn.execute("UPDATE limite_uso SET reseta_em = ?", (int(time.time()) - 10,))
        assert sentinela.pode_rodar_fundo(conn)[0]
        salvar_ajuste(conn, "preceptor_fundo", False)
        assert sentinela.pode_rodar_fundo(conn) == (False, "segundo plano desligado nos ajustes")


def test_motivo_de_ronda(ambiente):
    with conectar() as conn:
        aj = ajustes.todos(conn)
        s = sentinela.coletar(conn)
    manha = datetime.now().replace(hour=8)
    assert "primeira ronda" in maestro_mod.motivo_ronda(aj, s, manha)
    assert maestro_mod.motivo_ronda(aj, s, datetime.now().replace(hour=5)) is None
    s["segundo_plano"]["rondas_hoje"] = 1
    s["tentativas_desde_ultima_ronda"] = 30
    assert "30 respostas" in maestro_mod.motivo_ronda(aj, s, manha)
    s["segundo_plano"]["rondas_hoje"] = aj["max_rondas_dia"]
    assert maestro_mod.motivo_ronda(aj, s, manha) is None
    s["segundo_plano"]["rondas_hoje"] = 0
    s["dias_sem_estudar"], s["ultima_ronda"] = 5, datetime.now().astimezone().isoformat()
    assert maestro_mod.motivo_ronda(aj, s, manha) is None


async def test_maestro_roda_ronda_e_depois_tarefas(ambiente, fake_runner, monkeypatch):
    m = maestro_mod.Maestro(intervalo=1)
    with conectar() as conn:
        salvar_ajuste(conn, "hora_ronda", 0)
        conn.execute("INSERT INTO tarefas (agente, titulo, instrucoes) VALUES ('bibliotecario', 'PCDT', 'capturar')")
    assert (await m.tick()).startswith("ronda:")
    assert (await m.tick()).startswith("ocupado")
    await m.aguardar()
    ronda = fake_runner.pedidos[-1]
    assert ronda.papel == "preceptor" and ronda.fundo and ronda.prompt.startswith("RONDA")
    assert ronda.cwd.endswith("agentes/preceptor")
    with conectar() as conn:
        assert linha(conn, "SELECT conteudo_md FROM coach_insights WHERE tipo = 'analise'")["conteudo_md"].startswith("Ronda")
    assert (await m.tick()).startswith("tarefa #1")
    await m.aguardar()
    tarefa = fake_runner.pedidos[-1]
    assert tarefa.papel == "bibliotecario" and "TAREFA #1" in tarefa.prompt
    assert "mcp__lamina__biblioteca_capturar" in tarefa.permitidas
    with conectar() as conn:
        t = linha(conn, "SELECT * FROM tarefas WHERE id = 1")
        assert t["status"] == "concluida" and t["resultado"].startswith("Relatório")
    assert await m.tick() == "nada a fazer"
    with conectar() as conn:
        salvar_ajuste(conn, "orcamento_fundo_dia", 0)
    assert (await m.tick()).startswith("aguardando: orçamento")


async def test_tarefa_com_erro_fica_registrada(ambiente, fake_runner):
    fake_runner.respostas["bibliotecario"] = lambda p: RuntimeError("site fora do ar")
    with conectar() as conn:
        conn.execute("INSERT INTO tarefas (agente, titulo, instrucoes) VALUES ('bibliotecario', 'X', 'y')")
    m = maestro_mod.Maestro()
    assert m.disparar_tarefa(1)
    await m.aguardar()
    with conectar() as conn:
        assert linha(conn, "SELECT status FROM tarefas WHERE id = 1")["status"] == "erro"
    assert "site fora do ar" in m.ultimo_erro


def test_lembretes_automaticos_e_entrega(ambiente, monkeypatch):
    enviados = []
    monkeypatch.setattr(avisos, "notificador", lambda t, x: enviados.append(t) or True)
    with conectar() as conn:
        aj = ajustes.todos(conn)
        s = sentinela.coletar(conn)
        noite = datetime.now().replace(hour=20)
        assert avisos.lembretes_automaticos(conn, aj, s, datetime.now().replace(hour=9)) == []
        assert len(avisos.lembretes_automaticos(conn, aj, s, noite)) == 1
        assert avisos.lembretes_automaticos(conn, aj, s, noite) == []  # uma vez por dia
        aj["silencio"] = [0, 0]
        assert avisos.entregar_pendentes(conn, aj) == 1
        assert enviados == ["Meta do dia"]
        assert avisos.em_silencio({"silencio": [23, 7]}, datetime.now().replace(hour=2))
        assert not avisos.em_silencio({"silencio": [23, 7]}, datetime.now().replace(hour=12))


def test_api_do_preceptor_agenda_avisos_e_tarefas(cliente, fake_runner):
    estado = cliente.get("/api/preceptor").json()
    assert {"maestro", "sinais", "rondas", "acoes", "chats"} <= set(estado)
    hoje = datetime.now().date().isoformat()
    item = cliente.post("/api/agenda", json={"dia": hoje, "titulo": "Revisar sífilis", "tipo": "revisao"}).json()
    assert cliente.patch(f"/api/agenda/{item['id']}", json={"status": "feito"}).json()["status"] == "feito"
    assert cliente.get("/api/painel").json()["agenda_hoje"][0]["titulo"] == "Revisar sífilis"
    assert cliente.post("/api/agenda", json={"dia": hoje, "titulo": "x", "tipo": "festa"}).status_code == 422

    with conectar() as conn:
        avisos.criar(conn, titulo="Oi", texto="t")
        avisos.entregar_pendentes(conn, {"silencio": [0, 0], "notificacoes_desktop": False})
    av = cliente.get("/api/avisos").json()
    assert av["nao_lidos"] == 1
    cliente.post(f"/api/avisos/{av['itens'][0]['id']}/lido")
    assert cliente.get("/api/avisos").json()["nao_lidos"] == 0

    t = cliente.post("/api/tarefas", json={"titulo": "Capturar PCDT HAS", "instrucoes": "versão vigente"}).json()
    assert t["criado_por"] == "aluno" and t["status"] == "pendente"
    assert cliente.post(f"/api/tarefas/{t['id']}/cancelar").json()["ok"]
    assert cliente.post(f"/api/tarefas/{t['id']}/cancelar").status_code == 409
    assert cliente.post(f"/api/tarefas/{t['id']}/repetir").json()["ok"]
    assert cliente.post("/api/preceptor/pausa", json={"horas": 2}).json()["pausado_ate"]


def test_conversa_com_o_preceptor(cliente, fake_runner):
    chat = cliente.post("/api/preceptor/chats").json()["chat"]
    assert chat["agente"] == "preceptor"
    with cliente.stream("POST", f"/api/chats/{chat['id']}/mensagens", json={"texto": "Como estou indo?"}) as r:
        "".join(r.iter_text())
    p = fake_runner.pedidos[-1]
    assert p.papel == "preceptor" and "Sinais do momento" in p.prompt and "Preceptor" in p.sistema
    assert "mcp__lamina__tarefa_delegar" in p.permitidas
    estado = cliente.get("/api/preceptor").json()
    assert estado["chats"][0]["titulo"] == "Como estou indo?"
    assert cliente.get("/api/chats").json() == []  # conversas do Preceptor não aparecem no tutor livre


def test_conversa_recomeca_se_a_sessao_antiga_sumiu(cliente, fake_runner):
    fake_runner.respostas["tutor"] = (lambda p: RuntimeError("No conversation found") if p.retomar
                                      else "Resposta nova.")
    chat = cliente.post(f"/api/questoes/{Q}/chat").json()["chat"]
    with conectar() as conn:
        conn.execute("UPDATE chats SET session_id = 'sessao-velha' WHERE id = ?", (chat["id"],))
        conn.execute("INSERT INTO mensagens (chat_id, papel, conteudo) VALUES (?, 'user', 'pergunta antiga')", (chat["id"],))
        conn.execute("INSERT INTO mensagens (chat_id, papel, conteudo) VALUES (?, 'assistant', 'resposta antiga')",
                     (chat["id"],))
    with cliente.stream("POST", f"/api/chats/{chat['id']}/mensagens", json={"texto": "e agora?"}) as r:
        corpo = "".join(r.iter_text())
    assert '"tipo": "erro"' not in corpo
    ultimo = fake_runner.pedidos[-1]
    assert ultimo.retomar is None and "resposta antiga" in ultimo.prompt and "e agora?" in ultimo.prompt
    msgs = cliente.get(f"/api/chats/{chat['id']}").json()["mensagens"]
    assert msgs[-1]["conteudo"] == "Resposta nova."


def test_descricao_das_ferramentas_para_o_aluno(ambiente):
    d = runner_mod.descrever_ferramenta
    assert d("mcp__lamina__biblioteca_buscar", {"consulta": "sífilis"}) == "Biblioteca: buscando “sífilis”"
    caminho = str(config.BIBLIOTECA_DIR / "docs" / "x" / "texto.md")
    assert d("Read", {"file_path": caminho}) == "Biblioteca: lendo docs/x/texto.md"
    assert d("Write", {"file_path": str(config.AGENTES_DIR / "tutor" / "temas" / "a.md")}) == "Caderno: anotando em temas/a.md"
    assert d("Read", {"file_path": str(config.BANCO_DIR / "images" / "a.png")}) == "Examinando a imagem da questão"


async def test_freio_de_emergencia_interrompe_trabalho_de_fundo(ambiente, fake_runner):
    import asyncio

    liberar = asyncio.Event()
    original = fake_runner.executar

    async def lento(pedido):
        await liberar.wait()
        return await original(pedido)

    fake_runner.executar = lento
    with conectar() as conn:
        conn.execute("INSERT INTO tarefas (agente, titulo, instrucoes) VALUES ('bibliotecario', 'X', 'y')")
        salvar_ajuste(conn, "hora_ronda", 23)
    m = maestro_mod.Maestro()
    assert m.disparar_tarefa(1, fundo=True)
    await asyncio.sleep(0)
    with conectar() as conn:
        conn.execute("INSERT INTO limite_uso (id, status, utilizacao, reseta_em) VALUES (1, 'allowed_warning', 0.97, ?)",
                     (int(time.time()) + 3600,))
    assert (await m.tick()).startswith("interrompido")
    await m.aguardar()
    with conectar() as conn:
        assert linha(conn, "SELECT status FROM tarefas WHERE id = 1")["status"] == "pendente"
    assert m.ocupado is None and (await m.tick()).startswith("aguardando")
