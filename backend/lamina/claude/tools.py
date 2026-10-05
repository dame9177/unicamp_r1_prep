"""Ferramentas in-process (MCP do Agent SDK) que o coach usa para ler dados e agir no app.

Toda ação de escrita é registrada em `coach_acoes` com o necessário para desfazê-la.
O coach não altera status de domínio — isso é decisão do aluno.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from claude_agent_sdk import create_sdk_mcp_server, tool

from lamina import config, consultas
from lamina.claude import terminal
from lamina.db import conectar, linha, linhas
from lamina.domain import blocks, srs

PESO_MIN, PESO_MAX = 0.5, 2.0


@dataclass
class ContextoCoach:
    acoes: list[int] = field(default_factory=list)
    origem: str = "coach"  # quem está agindo (coach, tutor, juiz…), para o registro de ações


def _ok(dados) -> dict:
    texto = dados if isinstance(dados, str) else json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    return {"content": [{"type": "text", "text": texto}]}


def _erro(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}


def _pct(v):
    return None if v is None else round(v * 100)


def _registrar(conn, ctx: ContextoCoach, tipo: str, descricao: str, payload: dict, desfazer: dict) -> None:
    if ctx.origem != "coach":
        descricao = f"[{ctx.origem}] {descricao}"
    cur = conn.execute(
        "INSERT INTO coach_acoes (tipo, descricao, payload_json, desfazer_json) VALUES (?, ?, ?, ?)",
        (tipo, descricao, json.dumps(payload, ensure_ascii=False), json.dumps(desfazer, ensure_ascii=False)),
    )
    ctx.acoes.append(cur.lastrowid)


# ------------------------------------------------------------------------------------------------
# Leitura
# ------------------------------------------------------------------------------------------------


def dados_panorama(conn) -> dict:
    temas = consultas.estatisticas_temas(conn)
    temas_ord = sorted(temas, key=lambda t: -t["prioridade"])
    return {
        "hoje": date.today().isoformat(),
        "dias_ate_prova": config.dias_ate_prova(),
        "totais": consultas.totais(conn),
        "areas": [
            {"area": a["area"], "resp": a["respondidas"], "total": a["total"],
             "firme%": _pct(a["aproveitamento_firme"]), "bruto%": _pct(a["aproveitamento_bruto"]),
             "chutes": a["chutes"]}
            for a in consultas.estatisticas_areas(conn)
        ],
        "temas_por_prioridade": [
            {"id": t["id"], "nome": t["nome"], "area": t["area"], "n": t["total"], "resp": t["respondidas"],
             "firme%": _pct(t["aproveitamento_firme"]), "chutes": t["chutes"], "status": t["status"],
             "revisar": t["revisar"], "prev": round(t["prevalencia_norm"], 2), "prio": round(t["prioridade"], 3),
             "peso": t["peso_coach"]}
            for t in temas_ord
        ],
        "flashcards": {
            "total": linha(conn, "SELECT COUNT(*) AS n FROM flashcards WHERE suspenso = 0")["n"],
            "vencidos": consultas.flashcards_vencidos(conn),
        },
        "ritmo_ultimos_dias": consultas.serie_diaria(conn, 7),
        "blocos_abertos": linhas(conn, """
            SELECT b.id, b.nome, b.tipo, b.criado_por,
                   (SELECT COUNT(*) FROM bloco_questoes bq WHERE bq.bloco_id = b.id) AS n
            FROM blocos b WHERE b.arquivado = 0 AND b.finalizado_em IS NULL ORDER BY b.id DESC LIMIT 8"""),
    }


def dados_detalhe_tema(conn, tema_id: str) -> dict | None:
    tema = next((t for t in consultas.estatisticas_temas(conn) if t["id"] == tema_id), None)
    if not tema:
        return None
    ult = {r["questao_id"]: r for r in consultas.ultimas_tentativas(conn)}
    qs = linhas(conn, "SELECT id, processo, subtopico, tipo_cognitivo, enunciado FROM questoes "
                      "WHERE tema_id = ? AND anulada = 0 ORDER BY processo DESC", (tema_id,))
    return {
        "tema": {k: tema[k] for k in ("id", "nome", "area", "descricao", "total", "respondidas", "status",
                                       "aproveitamento_firme", "aproveitamento_bruto", "chutes", "peso_coach")},
        "questoes": [
            {"id": q["id"], "ano": q["processo"], "subtopico": q["subtopico"], "tipo": q["tipo_cognitivo"],
             "ultimo": (ult[q["id"]]["veredito"] if q["id"] in ult else None),
             "conf": (ult[q["id"]]["confianca"] if q["id"] in ult else None),
             "trecho": q["enunciado"][-160:]}
            for q in qs
        ],
    }


def dados_erros_recentes(conn, limite: int = 15) -> list[dict]:
    return linhas(conn, """
        SELECT t.questao_id, q.tema_id, q.subtopico, q.tipo_cognitivo, t.veredito, t.confianca,
               substr(t.resposta, 1, 120) AS resposta, t.faltou, q.obs_curadoria AS nota_atualizacao, t.criado_em
        FROM tentativas t JOIN questoes q ON q.id = t.questao_id
        WHERE t.veredito IN ('incorreto', 'parcial') OR (t.veredito = 'correto' AND t.confianca = 'chute')
        ORDER BY t.id DESC LIMIT ?""", (limite,))


def dados_buscar(conn, tema_id=None, area=None, texto=None, apenas_ineditas=False, limite=20) -> list[dict]:
    sql = ["SELECT q.id, q.tema_id, q.area, q.processo, q.subtopico, substr(q.enunciado, -140) AS trecho",
           "FROM questoes q WHERE q.anulada = 0"]
    params: list = []
    if tema_id:
        sql.append("AND q.tema_id = ?")
        params.append(tema_id)
    if area:
        sql.append("AND q.area = ?")
        params.append(area)
    if texto:
        sql.append("AND (q.enunciado LIKE ? OR q.subtopico LIKE ? OR q.resposta_esperada LIKE ?)")
        params += [f"%{texto}%"] * 3
    if apenas_ineditas:
        sql.append("AND NOT EXISTS (SELECT 1 FROM tentativas t WHERE t.questao_id = q.id)")
    sql.append("ORDER BY q.processo DESC LIMIT ?")
    params.append(min(int(limite), 50))
    return linhas(conn, " ".join(sql), params)


# ------------------------------------------------------------------------------------------------
# Servidor MCP
# ------------------------------------------------------------------------------------------------


def ferramentas_coach(ctx: ContextoCoach) -> list:
    @tool("panorama", "Resumo do desempenho: totais, áreas, temas ordenados por prioridade, flashcards, ritmo.", {})
    async def panorama(args):
        with conectar() as conn:
            return _ok(dados_panorama(conn))

    @tool("detalhe_tema", "Estatísticas e questões de um tema (com último veredito de cada questão).",
          {"tema_id": str})
    async def detalhe_tema(args):
        with conectar() as conn:
            d = dados_detalhe_tema(conn, args["tema_id"])
        return _ok(d) if d else _erro("tema inexistente")

    @tool("erros_recentes", "Últimos erros, parciais e acertos no chute (com o que faltou).", {"limite": int})
    async def erros_recentes(args):
        with conectar() as conn:
            return _ok(dados_erros_recentes(conn, int(args.get("limite") or 15)))

    @tool("buscar_questoes", "Busca questões por tema, área, texto ou apenas inéditas.", {
        "type": "object",
        "properties": {
            "tema_id": {"type": "string"}, "area": {"type": "string"}, "texto": {"type": "string"},
            "apenas_ineditas": {"type": "boolean"}, "limite": {"type": "integer"},
        },
    })
    async def buscar_questoes(args):
        with conectar() as conn:
            return _ok(dados_buscar(conn, args.get("tema_id"), args.get("area"), args.get("texto"),
                                    bool(args.get("apenas_ineditas")), args.get("limite") or 20))

    @tool("criar_bloco", "Cria um bloco de questões para o aluno resolver.", {
        "type": "object",
        "properties": {
            "nome": {"type": "string"}, "objetivo": {"type": "string"},
            "questao_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["nome", "objetivo", "questao_ids"],
    })
    async def criar_bloco(args):
        with conectar() as conn:
            validas = {r["id"] for r in linhas(conn, "SELECT id FROM questoes WHERE anulada = 0")}
            ids = [i for i in args["questao_ids"] if i in validas]
            if not ids:
                return _erro("nenhum id de questão válido")
            bid = blocks.criar_bloco(conn, args["nome"], "coach", ids, descricao=args["objetivo"], criado_por="coach")
            _registrar(conn, ctx, "criar_bloco", f"Criou o bloco “{args['nome']}” ({len(ids)} questões)",
                       {"bloco_id": bid, "objetivo": args["objetivo"]}, {"acao": "arquivar_bloco", "bloco_id": bid})
        return _ok({"bloco_id": bid, "questoes": len(ids)})

    @tool("ajustar_peso_tema", "Ajusta o peso de prioridade de um tema (0.5 a 2.0) com motivo.", {
        "type": "object",
        "properties": {"tema_id": {"type": "string"}, "peso": {"type": "number"}, "motivo": {"type": "string"}},
        "required": ["tema_id", "peso", "motivo"],
    })
    async def ajustar_peso_tema(args):
        peso = max(PESO_MIN, min(PESO_MAX, float(args["peso"])))
        with conectar() as conn:
            t = linha(conn, "SELECT * FROM temas WHERE id = ?", (args["tema_id"],))
            if not t:
                return _erro("tema inexistente")
            conn.execute("UPDATE temas SET peso_coach = ?, peso_motivo = ? WHERE id = ?",
                         (peso, args["motivo"], t["id"]))
            _registrar(conn, ctx, "ajustar_peso", f"Peso de “{t['nome']}”: {t['peso_coach']:g} → {peso:g}",
                       {"tema_id": t["id"], "peso": peso, "motivo": args["motivo"]},
                       {"acao": "restaurar_peso", "tema_id": t["id"], "peso": t["peso_coach"],
                        "motivo": t["peso_motivo"]})
        return _ok({"tema_id": t["id"], "peso": peso})

    @tool("publicar_missoes_do_dia", "Publica as missões de hoje (substitui as anteriores do dia).", {
        "type": "object",
        "properties": {
            "missoes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "titulo": {"type": "string"}, "detalhe": {"type": "string"},
                        "bloco_id": {"type": "integer"}, "tema_id": {"type": "string"},
                    },
                    "required": ["titulo"],
                },
            }
        },
        "required": ["missoes"],
    })
    async def publicar_missoes(args):
        with conectar() as conn:
            antigas = [r["id"] for r in linhas(
                conn, "SELECT id FROM coach_insights WHERE tipo = 'missao' AND arquivado = 0")]
            if antigas:
                conn.execute(f"UPDATE coach_insights SET arquivado = 1 WHERE id IN ({','.join('?' * len(antigas))})",
                             antigas)
            novas = []
            for m in args["missoes"][:8]:
                cur = conn.execute(
                    "INSERT INTO coach_insights (tipo, titulo, conteudo_md, payload_json) VALUES ('missao', ?, ?, ?)",
                    (m["titulo"], m.get("detalhe", ""),
                     json.dumps({k: m.get(k) for k in ("bloco_id", "tema_id") if m.get(k)}, ensure_ascii=False)),
                )
                novas.append(cur.lastrowid)
            _registrar(conn, ctx, "missoes", f"Publicou {len(novas)} missões para hoje", {"ids": novas},
                       {"acao": "trocar_insights", "arquivar": novas, "desarquivar": antigas})
        return _ok({"publicadas": len(novas)})

    @tool("publicar_insight", "Publica uma observação curta e acionável no painel.", {
        "type": "object",
        "properties": {
            "titulo": {"type": "string"}, "texto": {"type": "string"},
            "alerta": {"type": "boolean"},
        },
        "required": ["titulo", "texto"],
    })
    async def publicar_insight(args):
        tipo = "alerta" if args.get("alerta") else "insight"
        with conectar() as conn:
            cur = conn.execute("INSERT INTO coach_insights (tipo, titulo, conteudo_md) VALUES (?, ?, ?)",
                               (tipo, args["titulo"], args["texto"]))
            _registrar(conn, ctx, "insight", f"Publicou: {args['titulo']}", {"id": cur.lastrowid},
                       {"acao": "trocar_insights", "arquivar": [cur.lastrowid], "desarquivar": []})
        return _ok({"id": cur.lastrowid})

    @tool("criar_flashcards", "Cria flashcards (frente/verso) ligados a uma questão.", {
        "type": "object",
        "properties": {
            "questao_id": {"type": "string"},
            "cartoes": {"type": "array", "items": {
                "type": "object",
                "properties": {"frente": {"type": "string"}, "verso": {"type": "string"}},
                "required": ["frente", "verso"]}},
        },
        "required": ["questao_id", "cartoes"],
    })
    async def criar_flashcards(args):
        with conectar() as conn:
            q = linha(conn, "SELECT id, tema_id FROM questoes WHERE id = ?", (args["questao_id"],))
            if not q:
                return _erro("questão inexistente")
            ids = []
            for c in args["cartoes"][:6]:
                fsrs_json, due = srs.novo_cartao()
                cur = conn.execute(
                    "INSERT INTO flashcards (questao_id, tema_id, frente, verso, origem, fsrs_json, due) "
                    "VALUES (?, ?, ?, ?, 'coach', ?, ?)", (q["id"], q["tema_id"], c["frente"], c["verso"], fsrs_json, due))
                ids.append(cur.lastrowid)
            _registrar(conn, ctx, "flashcards", f"Criou {len(ids)} flashcards da questão {q['id']}", {"ids": ids},
                       {"acao": "remover_flashcards", "ids": ids})
        return _ok({"criados": len(ids)})

    @tool("terminal", terminal.DESCRICAO, {
        "type": "object",
        "properties": {"comando": {"type": "string"}, "tempo_max": {"type": "integer"}},
        "required": ["comando"],
    })
    async def terminal_tool(args):
        return _ok(await terminal.executar(args["comando"], int(args.get("tempo_max") or 30)))

    @tool("ver_questao", "Texto completo de uma questão do banco (caso, enunciado, gabarito oficial e notas).",
          {"questao_id": str})
    async def ver_questao(args):
        from lamina.claude.tasks import texto_questao

        with conectar() as conn:
            q = linha(conn, "SELECT * FROM questoes WHERE id = ?", (args["questao_id"],))
        return _ok(f"[{q['id']} · {q['area']}]\n{texto_questao(q)}") if q else _erro("questão inexistente")

    return [panorama, detalhe_tema, erros_recentes, buscar_questoes, criar_bloco, ajustar_peso_tema,
            publicar_missoes, publicar_insight, criar_flashcards, terminal_tool, ver_questao]


# Ferramentas por papel (nomes MCP). O coach recebe todas.
FERRAMENTAS_PAPEL = {
    "tutor": {"terminal", "ver_questao", "buscar_questoes", "criar_flashcards"},
    "juiz": {"terminal", "ver_questao"},
    "flashcards": {"terminal", "ver_questao"},
}


def servidor_para(papel: str, ctx: ContextoCoach):
    """Servidor MCP in-process com as ferramentas do papel + nomes para pré-aprovação."""
    ctx.origem = papel
    todas = ferramentas_coach(ctx)
    permitidas = FERRAMENTAS_PAPEL.get(papel)
    escolhidas = [t for t in todas if permitidas is None or t.name in permitidas]
    servidor = create_sdk_mcp_server(name="lamina", version="1.0.0", tools=escolhidas)
    return servidor, [f"mcp__lamina__{t.name}" for t in escolhidas]


def servidor_coach(ctx: ContextoCoach):
    return servidor_para("coach", ctx)


# ------------------------------------------------------------------------------------------------
# Desfazer
# ------------------------------------------------------------------------------------------------


def desfazer(conn, acao_id: int) -> bool:
    a = linha(conn, "SELECT * FROM coach_acoes WHERE id = ? AND desfeita_em IS NULL", (acao_id,))
    if not a:
        return False
    d = json.loads(a["desfazer_json"])
    match d.get("acao"):
        case "arquivar_bloco":
            conn.execute("UPDATE blocos SET arquivado = 1 WHERE id = ?", (d["bloco_id"],))
        case "restaurar_peso":
            conn.execute("UPDATE temas SET peso_coach = ?, peso_motivo = ? WHERE id = ?",
                         (d["peso"], d["motivo"], d["tema_id"]))
        case "trocar_insights":
            for i in d.get("arquivar", []):
                conn.execute("UPDATE coach_insights SET arquivado = 1 WHERE id = ?", (i,))
            for i in d.get("desarquivar", []):
                conn.execute("UPDATE coach_insights SET arquivado = 0 WHERE id = ?", (i,))
        case "remover_flashcards":
            for i in d.get("ids", []):
                conn.execute("DELETE FROM flashcards WHERE id = ?", (i,))
    conn.execute("UPDATE coach_acoes SET desfeita_em = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (acao_id,))
    return True
