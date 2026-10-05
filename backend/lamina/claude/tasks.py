"""Tarefas que usam o Claude: julgar respostas, gerar flashcards, tutor (chat) e coach."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from string import Template

from lamina import ajustes, config
from lamina.claude.runner import ErroClaude, Pedido, obter_runner
from lamina.db import conectar, linha, linhas

PROMPTS = Path(__file__).with_name("prompts")


def _vars() -> dict:
    p = config.carregar_perfil()
    perfil = ""
    if p.get("nome"):
        perfil += f" O nome do aluno é {p['nome']}."
    if p.get("especialidade_alvo"):
        perfil += f" O objetivo dele(a) é a residência em {p['especialidade_alvo']} (a prova é a mesma para todas as especialidades de acesso direto)."
    return {
        "hoje": date.today().strftime("%d/%m/%Y"),
        "data_prova": config.data_prova().strftime("%d/%m/%Y"),
        "dias": str(config.dias_ate_prova()),
        "perfil": perfil,
    }


def prompt(nome: str) -> str:
    return Template((PROMPTS / f"{nome}.md").read_text(encoding="utf-8")).safe_substitute(_vars())


def texto_questao(q: dict, gabarito: bool = True, imagens: bool = False) -> str:
    partes = []
    if q.get("enunciado_compartilhado"):
        partes.append(f"CASO CLÍNICO (compartilhado):\n{q['enunciado_compartilhado']}")
    partes.append(f"ENUNCIADO:\n{q['enunciado']}")
    if q.get("adaptada") and q.get("enunciado_original") and q["enunciado_original"] != q["enunciado"]:
        alts = json.loads(q["alternativas_json"] or "{}")
        alt_txt = "\n".join(f"{k.upper()}) {v}" for k, v in alts.items())
        partes.append(f"(Adaptada de múltipla escolha. Original:\n{q['enunciado_original']}\n{alt_txt}\nCorreta: {q['letra_original']})")
    elif q.get("alternativas_json") and not q.get("adaptada"):
        alts = json.loads(q["alternativas_json"])
        partes.append("ALTERNATIVAS ORIGINAIS:\n" + "\n".join(f"{k.upper()}) {v}" for k, v in alts.items()))
    if imagens:
        for img in json.loads(q.get("imagens_json") or "[]"):
            caminho = config.BANCO_DIR / img["arquivo"]
            legenda = f" — {img['legenda']}" if img.get("legenda") else ""
            partes.append(f"IMAGEM: {caminho}{legenda}")
    if gabarito:
        g = f"GABARITO OFICIAL (respostas esperadas):\n{q['resposta_esperada']}"
        aceitaveis = json.loads(q.get("aceitaveis_json") or "[]")
        if aceitaveis:
            g += "\nTambém aceitas: " + "; ".join(aceitaveis)
        if q.get("ampliado"):
            g += "\n(gabarito ampliado após recursos)"
        if q.get("obs_curadoria"):
            g += f"\nNOTA DE ATUALIZAÇÃO (curadoria): {q['obs_curadoria']}"
        partes.append(g)
    return "\n\n".join(partes)


def _questao(conn, questao_id: str) -> dict:
    q = linha(conn, "SELECT * FROM questoes WHERE id = ?", (questao_id,))
    if not q:
        raise KeyError(questao_id)
    return q


# ------------------------------------------------------------------------------------------------
# Kit de ferramentas comum a todas as instâncias do Claude
# ------------------------------------------------------------------------------------------------

def kit(papel: str) -> dict:
    """Ferramentas nativas (web, leitura do banco de questões) + MCP do app (terminal isolado etc.)."""
    from lamina.claude.tools import ContextoCoach, servidor_para

    ctx = ContextoCoach()
    servidor, nomes = servidor_para(papel, ctx)
    banco = str(config.BANCO_DIR)
    return {
        "ferramentas": ["WebSearch", "WebFetch", "Read"],
        "permitidas": ["WebSearch", "WebFetch", f"Read(/{banco}/**)", *nomes],
        "mcp": {"lamina": servidor},
        "diretorios_extras": [banco],
        "_ctx": ctx,
    }


def _sem_ctx(k: dict) -> dict:
    return {c: v for c, v in k.items() if not c.startswith("_")}


# ------------------------------------------------------------------------------------------------
# Juiz (dois estágios)
#   1. Haiku, sem ferramentas: compara com o gabarito da banca (rápido e barato).
#   2. Se houver indício de gabarito desatualizado: Sonnet com web search confirma a recomendação
#      vigente, decide por ela e escreve um adendo "gabarito da época × hoje".
# ------------------------------------------------------------------------------------------------

_ITEM_JUIZ = {
    "veredito": {"type": "string", "enum": ["correto", "parcial", "incorreto"]},
    "justificativa": {"type": "string"},
    "faltou": {"type": "string"},
    "resposta_modelo": {"type": "string"},
    "verificar_atualizacao": {"type": "boolean"},
    "adendo": {"type": "string"},
}
ESQUEMA_JUIZ = {
    "type": "object",
    "properties": _ITEM_JUIZ,
    "required": list(_ITEM_JUIZ),
    "additionalProperties": False,
}
ESQUEMA_JUIZ_LOTE = {
    "type": "object",
    "properties": {
        "resultados": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, **_ITEM_JUIZ},
                "required": ["id", *_ITEM_JUIZ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["resultados"],
    "additionalProperties": False,
}


def _aplicar_veredito(conn, tentativa_id: int, r: dict) -> None:
    conn.execute(
        """UPDATE tentativas SET veredito = ?, fonte_veredito = 'llm', justificativa = ?, faltou = ?,
             resposta_modelo = ?, adendo = ?, julgado_em = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
        (r["veredito"], r.get("justificativa"), r.get("faltou"), r.get("resposta_modelo"),
         (r.get("adendo") or "").strip() or None, tentativa_id),
    )


def _marcar_erro(tentativa_ids: list[int], msg: str) -> None:
    with conectar() as conn:
        for tid in tentativa_ids:
            conn.execute(
                "UPDATE tentativas SET veredito = 'erro', justificativa = ? WHERE id = ? AND veredito = 'pendente'",
                (msg, tid),
            )


def _prompt_julgamento(conn, tentativa_id: int) -> str:
    t = linha(conn, "SELECT * FROM tentativas WHERE id = ?", (tentativa_id,))
    q = _questao(conn, t["questao_id"])
    return (f"[Prova {q['prova_id']} — processo seletivo {q['processo']}]\n{texto_questao(q)}\n\n"
            f"RESPOSTA DO CANDIDATO:\n\"\"\"{t['resposta']}\"\"\"")


async def _julgar_atualizado(tentativa_id: int) -> dict:
    """Estágio 2: confirma a recomendação vigente na web e julga por ela."""
    with conectar() as conn:
        texto = _prompt_julgamento(conn, tentativa_id)
        modelo, esforco = ajustes.modelo(conn, "juiz_revisao"), ajustes.esforco(conn, "juiz_revisao")
        conn.execute("UPDATE tentativas SET veredito = 'pendente', justificativa = ? WHERE id = ?",
                     ("Verificando se o gabarito ainda vale pelas recomendações atuais…", tentativa_id))
    k = kit("juiz")
    r = await obter_runner().executar(Pedido(
        papel="juiz", modelo=modelo, esforco=esforco, sistema=prompt("juiz_atualizado"), esquema=ESQUEMA_JUIZ,
        ref=f"tentativa:{tentativa_id}:atualizacao", prompt=texto, max_turnos=12, **_sem_ctx(k),
    ))
    dados = r.estruturado or json.loads(r.texto)
    with conectar() as conn:
        _aplicar_veredito(conn, tentativa_id, dados)
    return dados


async def julgar_tentativa(tentativa_id: int, revisao: bool = False) -> dict:
    try:
        if revisao:
            return await _julgar_atualizado(tentativa_id)
        with conectar() as conn:
            texto = _prompt_julgamento(conn, tentativa_id)
            modelo = ajustes.modelo(conn, "juiz")
        r = await obter_runner().executar(Pedido(
            papel="juiz", modelo=modelo, sem_raciocinio=True, sistema=prompt("juiz"), esquema=ESQUEMA_JUIZ,
            ref=f"tentativa:{tentativa_id}", prompt=texto,
        ))
        dados = r.estruturado or json.loads(r.texto)
        if dados.get("verificar_atualizacao"):
            return await _julgar_atualizado(tentativa_id)
        with conectar() as conn:
            _aplicar_veredito(conn, tentativa_id, dados)
        return dados
    except (ErroClaude, json.JSONDecodeError) as exc:
        _marcar_erro([tentativa_id], str(exc))
        raise


async def julgar_lote(tentativa_ids: list[int], tamanho: int = 10) -> int:
    julgadas = 0
    verificar: list[int] = []
    for i in range(0, len(tentativa_ids), tamanho):
        lote = tentativa_ids[i:i + tamanho]
        with conectar() as conn:
            itens = [f"### ITEM id={tid}\n{_prompt_julgamento(conn, tid)}" for tid in lote]
            modelo = ajustes.modelo(conn, "juiz")
        pedido = Pedido(papel="juiz", modelo=modelo, sem_raciocinio=True, sistema=prompt("juiz_lote"),
                        esquema=ESQUEMA_JUIZ_LOTE, ref=f"lote:{lote[0]}-{lote[-1]}", prompt="\n\n".join(itens))
        try:
            r = await obter_runner().executar(pedido)
            dados = r.estruturado or json.loads(r.texto)
        except (ErroClaude, json.JSONDecodeError) as exc:
            _marcar_erro(lote, str(exc))
            continue
        with conectar() as conn:
            for item in dados["resultados"]:
                if item["id"] in lote:
                    _aplicar_veredito(conn, item["id"], item)
                    julgadas += 1
                    if item.get("verificar_atualizacao"):
                        verificar.append(item["id"])
    for tid in verificar:
        try:
            await _julgar_atualizado(tid)
        except (ErroClaude, json.JSONDecodeError):
            pass  # mantém o veredito do estágio 1
    return julgadas


# ------------------------------------------------------------------------------------------------
# Flashcards
# ------------------------------------------------------------------------------------------------

ESQUEMA_FLASHCARDS = {
    "type": "object",
    "properties": {
        "cartoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"frente": {"type": "string"}, "verso": {"type": "string"}},
                "required": ["frente", "verso"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cartoes"],
    "additionalProperties": False,
}


async def gerar_flashcards(questao_id: str, foco: str | None = None) -> list[dict]:
    with conectar() as conn:
        q = _questao(conn, questao_id)
        t = linha(conn, "SELECT * FROM tentativas WHERE questao_id = ? ORDER BY id DESC LIMIT 1", (questao_id,))
        nota = linha(conn, "SELECT explicacao_md FROM questao_notas WHERE questao_id = ?", (questao_id,))
        modelo, esforco = ajustes.modelo(conn, "flashcards"), ajustes.esforco(conn, "flashcards")
    partes = [texto_questao(q)]
    if t:
        partes.append(f"RESPOSTA DO ALUNO ({t['veredito']}, confiança: {t['confianca']}):\n{t['resposta']}")
        if t.get("faltou"):
            partes.append(f"O QUE FALTOU: {t['faltou']}")
    if nota and nota.get("explicacao_md"):
        partes.append(f"EXPLICAÇÃO FIXADA PELO ALUNO:\n{nota['explicacao_md'][:6000]}")
    if foco:
        partes.append(f"PEDIDO DO ALUNO: {foco}")
    r = await obter_runner().executar(Pedido(
        papel="flashcards", modelo=modelo, esforco=esforco, sistema=prompt("flashcards"),
        esquema=ESQUEMA_FLASHCARDS, ref=f"questao:{questao_id}", prompt="\n\n".join(partes),
        max_turnos=10, **_sem_ctx(kit("flashcards")),
    ))
    dados = r.estruturado or json.loads(r.texto)
    return dados["cartoes"]


# ------------------------------------------------------------------------------------------------
# Tutor (chat lateral com streaming)
# ------------------------------------------------------------------------------------------------

def _contexto_inicial(conn, questao_id: str) -> str:
    q = _questao(conn, questao_id)
    t = linha(conn, "SELECT * FROM tentativas WHERE questao_id = ? ORDER BY id DESC LIMIT 1", (questao_id,))
    partes = [f"[Questão {q['id']} — {q['area']} — prova {q['prova_id']}]", texto_questao(q, imagens=True)]
    if t:
        partes.append(
            f"RESPOSTA DO ALUNO: {t['resposta']}\nConfiança declarada: {t['confianca']}\n"
            f"Veredito: {t['veredito']}" + (f" — {t['justificativa']}" if t.get("justificativa") else "")
        )
    return "\n\n".join(partes)


async def conversar(chat_id: int, mensagem: str) -> AsyncIterator[dict]:
    with conectar() as conn:
        chat = linha(conn, "SELECT * FROM chats WHERE id = ?", (chat_id,))
        if not chat:
            raise KeyError(chat_id)
        modelo = chat["modelo"] or ajustes.modelo(conn, "tutor")
        esforco = ajustes.esforco(conn, "tutor")
        primeira = chat["session_id"] is None
        contexto = _contexto_inicial(conn, chat["questao_id"]) if (primeira and chat["questao_id"]) else ""
        conn.execute("INSERT INTO mensagens (chat_id, papel, conteudo) VALUES (?, 'user', ?)", (chat_id, mensagem))

    texto_prompt = f"{contexto}\n\n---\nPERGUNTA DO ALUNO:\n{mensagem}" if contexto else mensagem
    pedido = Pedido(
        papel="tutor", modelo=modelo, esforco=esforco, sistema=prompt("tutor"), prompt=texto_prompt,
        retomar=chat["session_id"], ref=f"chat:{chat_id}", **_sem_ctx(kit("tutor")),
    )
    atividades: list[str] = []
    async for ev in obter_runner().transmitir(pedido):
        if ev["tipo"] == "atividade":
            atividades.append(ev["detalhe"])
        elif ev["tipo"] == "fim":
            with conectar() as conn:
                cur = conn.execute(
                    "INSERT INTO mensagens (chat_id, papel, conteudo, atividades_json, job_id) VALUES (?, 'assistant', ?, ?, ?)",
                    (chat_id, ev["texto"], json.dumps(atividades, ensure_ascii=False), ev.get("job_id")),
                )
                ev = {**ev, "mensagem_id": cur.lastrowid}
                conn.execute(
                    "UPDATE chats SET session_id = ?, modelo = ?, atualizado_em = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                    (ev.get("session_id") or chat["session_id"], modelo, chat_id),
                )
        yield ev


# ------------------------------------------------------------------------------------------------
# Coach
# ------------------------------------------------------------------------------------------------

async def analisar_coach(pedido_extra: str | None = None) -> dict:
    from lamina.claude.tools import ContextoCoach

    with conectar() as conn:
        modelo, esforco = ajustes.modelo(conn, "coach"), ajustes.esforco(conn, "coach")
    k = kit("coach")
    ctx: ContextoCoach = k["_ctx"]
    texto = "Analise meu desempenho e organize meu estudo de hoje."
    if pedido_extra:
        texto += f"\n\nObservação do aluno: {pedido_extra}"
    r = await obter_runner().executar(Pedido(
        papel="coach", modelo=modelo, esforco=esforco, sistema=prompt("coach"), prompt=texto,
        ref="coach", max_turnos=20, **_sem_ctx(k),
    ))
    with conectar() as conn:
        if ctx.acoes:
            conn.execute(
                f"UPDATE coach_acoes SET job_id = ? WHERE id IN ({','.join('?' * len(ctx.acoes))})",
                (r.job_id, *ctx.acoes),
            )
        cur = conn.execute(
            "INSERT INTO coach_insights (tipo, titulo, conteudo_md, job_id) VALUES ('analise', ?, ?, ?)",
            (f"Análise de {date.today().strftime('%d/%m')}", r.texto, r.job_id),
        )
    return {"analise_id": cur.lastrowid, "texto": r.texto, "acoes": len(ctx.acoes), "job_id": r.job_id}


def ultima_analise(conn) -> dict | None:
    return linha(conn, "SELECT * FROM coach_insights WHERE tipo = 'analise' ORDER BY id DESC LIMIT 1")


def tentativas_desde_ultima_analise(conn) -> int:
    ult = ultima_analise(conn)
    desde = ult["criado_em"] if ult else "1970-01-01"
    return linha(conn, "SELECT COUNT(*) AS n FROM tentativas WHERE criado_em > ?", (desde,))["n"]


def jobs_hoje(conn) -> list[dict]:
    return linhas(conn, """
        SELECT papel, COUNT(*) AS chamadas, SUM(input_tokens + output_tokens + cache_read + cache_write) AS tokens,
               SUM(custo_usd) AS custo_usd
        FROM llm_jobs WHERE date(criado_em) = date('now') GROUP BY papel""")
