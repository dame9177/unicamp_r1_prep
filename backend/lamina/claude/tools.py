"""Ferramentas in-process (MCP do Agent SDK) dos agentes: dados do aluno, ações no app, biblioteca,
histórico de conversas e orquestração (agenda, avisos, tarefas).

Cada papel recebe um subconjunto (FERRAMENTAS_PAPEL); o Preceptor recebe todas.
Toda ação de escrita no estudo do aluno é registrada em `coach_acoes` com o necessário para desfazê-la.
Nenhum agente altera status de domínio: isso é decisão do aluno.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from claude_agent_sdk import create_sdk_mcp_server, tool

from lamina import agentes, config, consultas
from lamina.biblioteca import armazem
from lamina.biblioteca.captura import ErroCaptura
from lamina.claude import terminal
from lamina.db import conectar, linha, linhas
from lamina.domain import blocks, srs

PESO_MIN, PESO_MAX = 0.5, 2.0


@dataclass
class Contexto:
    acoes: list[int] = field(default_factory=list)
    origem: str = "preceptor"  # papel que está agindo (preceptor, tutor, juiz…), para o registro de ações

    @property
    def agente(self) -> str:
        return agentes.agente_de(self.origem)


ContextoCoach = Contexto  # nome antigo


def _ok(dados) -> dict:
    texto = dados if isinstance(dados, str) else json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    return {"content": [{"type": "text", "text": texto}]}


def _erro(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}


def _pct(v):
    return None if v is None else round(v * 100)


def _registrar(conn, ctx: Contexto, tipo: str, descricao: str, payload: dict, desfazer: dict) -> None:
    if ctx.origem not in ("coach", "preceptor"):
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


def ferramentas_estudo(ctx: Contexto) -> list:
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
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (q["id"], q["tema_id"], c["frente"], c["verso"], "tutor" if ctx.origem == "tutor" else "coach",
                     fsrs_json, due))
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
        return _ok(await terminal.executar(args["comando"], int(args.get("tempo_max") or 30), ctx.agente))

    @tool("ver_questao", "Texto completo de uma questão do banco (caso, enunciado, gabarito oficial e notas).",
          {"questao_id": str})
    async def ver_questao(args):
        from lamina.claude.tasks import texto_questao

        with conectar() as conn:
            q = linha(conn, "SELECT * FROM questoes WHERE id = ?", (args["questao_id"],))
        return _ok(f"[{q['id']} · {q['area']}]\n{texto_questao(q)}") if q else _erro("questão inexistente")

    return [panorama, detalhe_tema, erros_recentes, buscar_questoes, criar_bloco, ajustar_peso_tema,
            publicar_missoes, publicar_insight, criar_flashcards, terminal_tool, ver_questao]


# ------------------------------------------------------------------------------------------------
# Biblioteca e histórico
# ------------------------------------------------------------------------------------------------

_CONF = ["oficial", "sociedade", "literatura"]


def ferramentas_biblioteca(ctx: Contexto) -> list:
    @tool("biblioteca_buscar",
          "Busca em texto completo na biblioteca compartilhada (documentos oficiais integrais e notas verificadas "
          "guardados por todos os agentes). Devolve trechos com id e local (página/seção). Use ANTES da web.", {
              "type": "object",
              "properties": {
                  "consulta": {"type": "string", "description": "termos-chave, ex.: 'sífilis gestante tratamento'"},
                  "limite": {"type": "integer"},
                  "confiabilidade": {"type": "string", "enum": [*_CONF, "nota"]},
                  "tipo": {"type": "string", "enum": ["documento", "nota"]},
              },
              "required": ["consulta"],
          })
    async def biblioteca_buscar(args):
        with conectar() as conn:
            r = armazem.buscar(conn, args["consulta"], int(args.get("limite") or 8), args.get("confiabilidade"),
                               args.get("tipo"))
        if not r:
            return _ok("Nada encontrado na biblioteca para esses termos. Tente sinônimos ou pesquise na web e "
                       "capture o documento oficial com biblioteca_capturar.")
        return _ok(r)

    @tool("biblioteca_ler",
          "Lê um documento da biblioteca: por página (pagina/ate_pagina, em PDFs), em volta de um trecho de texto "
          "(trecho) ou a partir de um caractere (inicio). Até 40 mil caracteres por chamada (padrão 12 mil).", {
              "type": "object",
              "properties": {
                  "id": {"type": "string"}, "pagina": {"type": "integer"}, "ate_pagina": {"type": "integer"},
                  "trecho": {"type": "string"}, "inicio": {"type": "integer"}, "max_caracteres": {"type": "integer"},
              },
              "required": ["id"],
          })
    async def biblioteca_ler(args):
        try:
            with conectar() as conn:
                return _ok(armazem.ler(conn, args["id"], args.get("pagina"), args.get("ate_pagina"),
                                       args.get("trecho"), args.get("inicio") or 0, args.get("max_caracteres") or 12_000))
        except KeyError:
            return _erro("id inexistente; veja biblioteca_catalogo")
        except ValueError as exc:
            return _erro(str(exc))

    @tool("biblioteca_catalogo", "Lista os itens da biblioteca (id, título, órgão, ano, confiabilidade, status).", {
        "type": "object",
        "properties": {"busca": {"type": "string"}, "tipo": {"type": "string", "enum": ["documento", "nota"]}},
    })
    async def biblioteca_catalogo(args):
        with conectar() as conn:
            itens = armazem.catalogo(conn, args.get("tipo"), args.get("busca"))
        return _ok([{k: i[k] for k in ("id", "tipo", "titulo", "orgao", "ano", "categoria", "confiabilidade",
                                       "status", "paginas", "temas")} for i in itens[:150]])

    @tool("biblioteca_capturar",
          "Baixa um documento da web (PDF ou página) e guarda o TEXTO INTEGRAL na biblioteca, indexado para todos os "
          "agentes. Use para referências confiáveis (gov.br/saude, CONITEC, sociedades brasileiras, SciELO, "
          "periódicos). Devolve id, páginas e sumário (não o texto): depois leia com biblioteca_ler, Grep ou Read. "
          "Se a URL for uma página-índice, devolve os links de documentos encontrados nela.", {
              "type": "object",
              "properties": {
                  "url": {"type": "string"},
                  "titulo": {"type": "string", "description": "título oficial do documento"},
                  "orgao": {"type": "string", "description": "ex.: Ministério da Saúde, CONITEC, SBP, FEBRASGO"},
                  "ano": {"type": "integer", "description": "ano de publicação/edição"},
                  "categoria": {"type": "string",
                                "description": "pcdt, protocolo, guia, manual, diretriz, nota_tecnica, calendario, "
                                               "caderno_atencao_basica, artigo, consenso, outro"},
                  "confiabilidade": {"type": "string", "enum": _CONF,
                                     "description": "oficial = governo/CONITEC; sociedade = sociedade médica; "
                                                    "literatura = artigos, livros, outros"},
                  "temas": {"type": "array", "items": {"type": "string"}, "description": "ids de temas do app"},
                  "resumo": {"type": "string", "description": "1-2 frases: do que trata e para que serve"},
                  "substituir": {"type": "boolean", "description": "recapturar se a URL já existe"},
              },
              "required": ["url", "titulo", "orgao", "confiabilidade"],
          })
    async def biblioteca_capturar(args):
        try:
            r = await armazem.capturar(
                args["url"], criado_por=ctx.origem, titulo=args.get("titulo"), orgao=args.get("orgao"),
                ano=args.get("ano"), categoria=args.get("categoria"), confiabilidade=args.get("confiabilidade"),
                temas=args.get("temas"), resumo=args.get("resumo"), substituir=bool(args.get("substituir")))
        except (ErroCaptura, ValueError) as exc:
            return _erro(f"Não foi possível capturar: {exc}")
        return _ok(r)

    @tool("biblioteca_publicar_nota",
          "Publica (ou atualiza, passando id) uma nota-síntese verificada na biblioteca, visível a todos os agentes e "
          "ao aluno. Cada afirmação precisa vir das fontes citadas no texto como [id-do-documento, p. N] ou link. "
          "Use para condensar o que é cobrável de um tema a partir de documentos oficiais.", {
              "type": "object",
              "properties": {
                  "titulo": {"type": "string"}, "conteudo_md": {"type": "string"},
                  "fontes": {"type": "array", "items": {"type": "string"},
                             "description": "ids de documentos da biblioteca e/ou URLs consultadas"},
                  "temas": {"type": "array", "items": {"type": "string"}}, "resumo": {"type": "string"},
                  "id": {"type": "string", "description": "id de uma nota existente para atualizá-la"},
              },
              "required": ["titulo", "conteudo_md", "fontes"],
          })
    async def biblioteca_publicar_nota(args):
        try:
            with conectar() as conn:
                r = armazem.salvar_nota(conn, titulo=args["titulo"], conteudo=args["conteudo_md"],
                                        fontes=args["fontes"], criado_por=ctx.origem, temas=args.get("temas"),
                                        resumo=args.get("resumo"), nota_id=args.get("id"))
        except KeyError:
            return _erro("nota inexistente")
        except ValueError as exc:
            return _erro(str(exc))
        return _ok(r)

    @tool("biblioteca_marcar", "Marca um item como vigente, substituido (ex.: saiu nova edição) ou em_revisao.", {
        "type": "object",
        "properties": {"id": {"type": "string"}, "status": {"type": "string", "enum": list(armazem.STATUS)},
                       "motivo": {"type": "string"}},
        "required": ["id", "status", "motivo"],
    })
    async def biblioteca_marcar(args):
        try:
            with conectar() as conn:
                armazem.marcar(conn, args["id"], args["status"], f"[{ctx.origem}] {args['motivo']}")
        except KeyError:
            return _erro("id inexistente")
        return _ok({"ok": True})

    @tool("historico_conversas",
          "Busca nas suas conversas anteriores com o aluno (o que ele perguntou e o que você respondeu).", {
              "type": "object",
              "properties": {"consulta": {"type": "string"}, "limite": {"type": "integer"}},
              "required": ["consulta"],
          })
    async def historico_conversas(args):
        termos = [t for t in re.findall(r"\w+", args["consulta"].lower()) if len(t) > 2][:6]
        if not termos:
            return _erro("consulta vazia")
        filtro = " AND ".join("lower(m.conteudo) LIKE ?" for _ in termos)
        with conectar() as conn:
            achados = linhas(conn, f"""
                SELECT m.chat_id, c.questao_id, m.papel, m.criado_em, m.conteudo
                FROM mensagens m JOIN chats c ON c.id = m.chat_id
                WHERE c.agente = ? AND {filtro} ORDER BY m.id DESC LIMIT ?""",
                (ctx.agente, *[f"%{t}%" for t in termos], min(int(args.get("limite") or 6), 15)))
        for a in achados:
            texto = a.pop("conteudo")
            pos = max(0, texto.lower().find(termos[0]) - 300)
            a["trecho"] = texto[pos:pos + 900]
        return _ok(achados or "Nada encontrado nas conversas anteriores.")

    return [biblioteca_buscar, biblioteca_ler, biblioteca_catalogo, biblioteca_capturar, biblioteca_publicar_nota,
            biblioteca_marcar, historico_conversas]


# ------------------------------------------------------------------------------------------------
# Orquestração (Preceptor): sinais, agenda, avisos e tarefas para outros agentes
# ------------------------------------------------------------------------------------------------

TIPOS_AGENDA = ["estudo", "revisao", "simulado", "flashcards", "leitura", "descanso"]
AGENTES_DELEGAVEIS = ["bibliotecario"]


def para_utc(quando: str | None) -> str:
    """Data/hora local (ISO, sem fuso) → ISO UTC. Vazio = agora."""
    if not quando:
        dt = datetime.now(UTC)
    else:
        dt = datetime.fromisoformat(quando)
        dt = dt.astimezone(UTC) if dt.tzinfo else dt.astimezone().astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ferramentas_orquestracao(ctx: Contexto) -> list:
    @tool("sinais", "Sinais objetivos do momento: meta do dia, flashcards vencidos, dias sem estudar, agenda de hoje, "
                    "temas a revisar, tarefas, avisos e orçamento do segundo plano.", {})
    async def sinais(args):
        from lamina.orquestra import sentinela

        with conectar() as conn:
            return _ok(sentinela.coletar(conn))

    @tool("agenda_ver", "Agenda de estudos entre duas datas (padrão: hoje até +7 dias).", {
        "type": "object", "properties": {"de": {"type": "string"}, "ate": {"type": "string"}},
    })
    async def agenda_ver(args):
        de = args.get("de") or date.today().isoformat()
        ate = args.get("ate") or (date.today() + timedelta(days=7)).isoformat()
        with conectar() as conn:
            return _ok(linhas(conn, "SELECT id, dia, titulo, tipo, detalhe, tema_id, bloco_id, minutos, status, origem "
                                    "FROM agenda WHERE dia BETWEEN ? AND ? ORDER BY dia, id", (de, ate)))

    @tool("agenda_planejar",
          "Define o plano de estudo de um ou mais dias. Para cada dia informado, substitui os itens PLANEJADOS que "
          "você criou antes; itens do aluno e itens já feitos/pulados ficam.", {
              "type": "object",
              "properties": {"dias": {"type": "array", "items": {
                  "type": "object",
                  "properties": {
                      "dia": {"type": "string", "description": "AAAA-MM-DD"},
                      "itens": {"type": "array", "items": {
                          "type": "object",
                          "properties": {
                              "titulo": {"type": "string"}, "tipo": {"type": "string", "enum": TIPOS_AGENDA},
                              "detalhe": {"type": "string"}, "tema_id": {"type": "string"},
                              "bloco_id": {"type": "integer"}, "minutos": {"type": "integer"},
                          },
                          "required": ["titulo", "tipo"]}},
                  },
                  "required": ["dia", "itens"]}}},
              "required": ["dias"],
          })
    async def agenda_planejar(args):
        removidos, novos = [], []
        with conectar() as conn:
            temas_validos = {r["id"] for r in linhas(conn, "SELECT id FROM temas")}
            for d in args["dias"][:21]:
                dia = date.fromisoformat(d["dia"]).isoformat()
                antigos = linhas(conn, "SELECT * FROM agenda WHERE dia = ? AND origem = 'preceptor' "
                                       "AND status = 'planejado'", (dia,))
                removidos += antigos
                conn.execute("DELETE FROM agenda WHERE dia = ? AND origem = 'preceptor' AND status = 'planejado'", (dia,))
                for it in d["itens"][:10]:
                    cur = conn.execute(
                        "INSERT INTO agenda (dia, titulo, detalhe, tipo, tema_id, bloco_id, minutos) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (dia, it["titulo"], it.get("detalhe"), it["tipo"] if it["tipo"] in TIPOS_AGENDA else "estudo",
                         it.get("tema_id") if it.get("tema_id") in temas_validos else None, it.get("bloco_id"),
                         it.get("minutos")))
                    novos.append(cur.lastrowid)
            dias = sorted({d["dia"] for d in args["dias"]})
            _registrar(conn, ctx, "agenda", f"Planejou a agenda de {len(dias)} dia(s) ({len(novos)} itens)",
                       {"dias": dias}, {"acao": "restaurar_agenda", "remover": novos, "restaurar": removidos})
        return _ok({"itens": len(novos)})

    @tool("aviso_agendar",
          "Agenda um aviso para o aluno: notificação no desktop e no sino do app. Use com parcimônia (no máximo 2-3 "
          "por dia): lembretes com hora marcada, sugestões oportunas, alertas e relatórios.", {
              "type": "object",
              "properties": {
                  "titulo": {"type": "string"}, "texto": {"type": "string"},
                  "quando": {"type": "string", "description": "data/hora local AAAA-MM-DDTHH:MM; vazio = agora"},
                  "tipo": {"type": "string", "enum": ["lembrete", "sugestao", "alerta", "relatorio"]},
                  "link": {"type": "string", "description": "rota do app, ex.: /blocos/12, /flashcards, /agenda"},
              },
              "required": ["titulo", "texto"],
          })
    async def aviso_agendar(args):
        try:
            quando = para_utc(args.get("quando"))
        except ValueError:
            return _erro("quando inválido; use AAAA-MM-DDTHH:MM")
        link = args.get("link") if str(args.get("link") or "").startswith("/") else None
        with conectar() as conn:
            cur = conn.execute("INSERT INTO avisos (tipo, titulo, texto, link, origem, quando) VALUES (?, ?, ?, ?, ?, ?)",
                               (args.get("tipo") or "lembrete", args["titulo"], args["texto"], link, ctx.origem, quando))
            _registrar(conn, ctx, "aviso", f"Agendou o aviso “{args['titulo']}”", {"id": cur.lastrowid},
                       {"acao": "descartar_aviso", "id": cur.lastrowid})
        return _ok({"id": cur.lastrowid, "quando_utc": quando})

    @tool("tarefa_delegar",
          "Delega uma tarefa a outro agente, executada em segundo plano dentro do orçamento (uma por vez). Hoje: "
          "'bibliotecario' (capturar documentos oficiais, verificar vigência, escrever notas-síntese).", {
              "type": "object",
              "properties": {
                  "agente": {"type": "string", "enum": AGENTES_DELEGAVEIS}, "titulo": {"type": "string"},
                  "instrucoes": {"type": "string", "description": "objetivo, escopo, fontes preferidas, entregáveis"},
                  "prioridade": {"type": "integer", "description": "1 alta, 2 normal, 3 baixa"},
              },
              "required": ["agente", "titulo", "instrucoes"],
          })
    async def tarefa_delegar(args):
        if args["agente"] not in AGENTES_DELEGAVEIS:
            return _erro(f"agente deve ser um de {AGENTES_DELEGAVEIS}")
        prioridade = min(3, max(1, int(args.get("prioridade") or 2)))
        with conectar() as conn:
            pendentes = linha(conn, "SELECT COUNT(*) AS n FROM tarefas WHERE status = 'pendente'")["n"]
            if pendentes >= 12:
                return _erro("a fila já tem 12 tarefas pendentes; espere ou cancele algumas")
            cur = conn.execute("INSERT INTO tarefas (agente, titulo, instrucoes, prioridade, criado_por) "
                               "VALUES (?, ?, ?, ?, ?)",
                               (args["agente"], args["titulo"], args["instrucoes"], prioridade, ctx.origem))
            _registrar(conn, ctx, "tarefa", f"Delegou ao {args['agente']}: {args['titulo']}", {"id": cur.lastrowid},
                       {"acao": "cancelar_tarefa", "id": cur.lastrowid})
        return _ok({"id": cur.lastrowid, "na_fila": pendentes + 1})

    @tool("tarefas_ver", "Fila de tarefas dos agentes (pendentes e as 10 últimas concluídas, com resultado).", {})
    async def tarefas_ver(args):
        with conectar() as conn:
            return _ok({
                "pendentes": linhas(conn, "SELECT id, agente, titulo, prioridade, status, criado_em FROM tarefas "
                                          "WHERE status IN ('pendente', 'executando') ORDER BY prioridade, id"),
                "recentes": linhas(conn, "SELECT id, agente, titulo, status, substr(resultado, 1, 600) AS resultado, "
                                         "concluido_em FROM tarefas WHERE status NOT IN ('pendente', 'executando') "
                                         "ORDER BY id DESC LIMIT 10"),
            })

    return [sinais, agenda_ver, agenda_planejar, aviso_agendar, tarefa_delegar, tarefas_ver]


def todas_ferramentas(ctx: Contexto) -> list:
    return ferramentas_estudo(ctx) + ferramentas_biblioteca(ctx) + ferramentas_orquestracao(ctx)


ferramentas_coach = todas_ferramentas  # nome antigo

# Ferramentas por papel (nomes MCP). O Preceptor (admin) recebe todas.
_BIB_LER = {"biblioteca_buscar", "biblioteca_ler", "biblioteca_catalogo"}
_BIB_ESCREVER = {"biblioteca_capturar", "biblioteca_publicar_nota"}
FERRAMENTAS_PAPEL: dict[str, set[str] | None] = {
    "tutor": {"terminal", "ver_questao", "buscar_questoes", "criar_flashcards", "historico_conversas",
              *_BIB_LER, *_BIB_ESCREVER},
    "juiz": {"terminal", "ver_questao", "biblioteca_capturar", *_BIB_LER},
    "flashcards": {"terminal", "ver_questao", *_BIB_LER},
    "bibliotecario": {"terminal", "panorama", "detalhe_tema", "buscar_questoes", "ver_questao", "biblioteca_marcar",
                      *_BIB_LER, *_BIB_ESCREVER},
    "preceptor": None,
}


def servidor_para(papel: str, ctx: Contexto):
    """Servidor MCP in-process com as ferramentas do papel + nomes para pré-aprovação."""
    ctx.origem = papel
    permitidas = FERRAMENTAS_PAPEL.get(papel, set())
    escolhidas = [t for t in todas_ferramentas(ctx) if permitidas is None or t.name in permitidas]
    servidor = create_sdk_mcp_server(name="lamina", version="1.0.0", tools=escolhidas)
    return servidor, [f"mcp__lamina__{t.name}" for t in escolhidas]


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
        case "restaurar_agenda":
            for i in d.get("remover", []):
                conn.execute("DELETE FROM agenda WHERE id = ? AND status = 'planejado'", (i,))
            for it in d.get("restaurar", []):  # com o id original, para desfazer em cadeia funcionar
                conn.execute("INSERT OR IGNORE INTO agenda (id, dia, titulo, detalhe, tipo, tema_id, bloco_id, minutos, "
                             "status, origem, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (it["id"], it["dia"], it["titulo"], it["detalhe"], it["tipo"], it["tema_id"],
                              it["bloco_id"], it["minutos"], it["status"], it["origem"], it["criado_em"]))
        case "descartar_aviso":
            conn.execute("UPDATE avisos SET status = 'descartado' WHERE id = ?", (d["id"],))
        case "cancelar_tarefa":
            conn.execute("UPDATE tarefas SET status = 'cancelada' WHERE id = ? AND status = 'pendente'", (d["id"],))
    conn.execute("UPDATE coach_acoes SET desfeita_em = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (acao_id,))
    return True
