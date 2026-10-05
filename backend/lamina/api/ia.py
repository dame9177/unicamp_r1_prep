"""Rotas que envolvem o Claude (conversas, flashcards) e as de ajustes/uso. O Preceptor fica em orquestra.py."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lamina import ajustes, config
from lamina.api.comum import obter_ou_404
from lamina.claude import tasks
from lamina.claude.runner import ErroClaude
from lamina.orquestra import sentinela
from lamina.db import conectar, linha, linhas
from lamina.domain import srs

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------------------------------------
# Tutor
# ------------------------------------------------------------------------------------------------


def _chat_completo(conn, chat: dict) -> dict:
    msgs = linhas(conn, "SELECT id, papel, conteudo, atividades_json, criado_em FROM mensagens "
                        "WHERE chat_id = ? ORDER BY id", (chat["id"],))
    for m in msgs:
        m["atividades"] = json.loads(m.pop("atividades_json") or "[]")
    return {"chat": chat, "mensagens": msgs}


@router.post("/questoes/{questao_id}/chat")
def abrir_chat(questao_id: str, novo: bool = False):
    with conectar() as conn:
        obter_ou_404(conn, "SELECT id FROM questoes WHERE id = ?", (questao_id,), "questão")
        chat = None if novo else linha(
            conn, "SELECT * FROM chats WHERE questao_id = ? AND agente = 'tutor' ORDER BY id DESC LIMIT 1", (questao_id,))
        if not chat:
            cur = conn.execute("INSERT INTO chats (questao_id) VALUES (?)", (questao_id,))
            chat = linha(conn, "SELECT * FROM chats WHERE id = ?", (cur.lastrowid,))
        return _chat_completo(conn, chat)


@router.get("/chats")
def listar_chats_gerais():
    with conectar() as conn:
        return linhas(conn, """
            SELECT c.id, c.criado_em, c.atualizado_em,
                   (SELECT conteudo FROM mensagens m WHERE m.chat_id = c.id AND m.papel = 'user' ORDER BY m.id LIMIT 1) AS titulo
            FROM chats c WHERE c.questao_id IS NULL AND c.agente = 'tutor' ORDER BY c.atualizado_em DESC LIMIT 50""")


@router.post("/chats")
def novo_chat_geral():
    with conectar() as conn:
        cur = conn.execute("INSERT INTO chats (questao_id) VALUES (NULL)")
        return _chat_completo(conn, linha(conn, "SELECT * FROM chats WHERE id = ?", (cur.lastrowid,)))


@router.get("/chats/{chat_id}")
def obter_chat(chat_id: int):
    with conectar() as conn:
        return _chat_completo(conn, obter_ou_404(conn, "SELECT * FROM chats WHERE id = ?", (chat_id,), "chat"))


class Mensagem(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)


@router.post("/chats/{chat_id}/mensagens")
async def enviar_mensagem(chat_id: int, dados: Mensagem):
    with conectar() as conn:
        obter_ou_404(conn, "SELECT id FROM chats WHERE id = ?", (chat_id,), "chat")

    async def eventos():
        try:
            async for ev in tasks.conversar(chat_id, dados.texto):
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'tipo': 'erro', 'mensagem': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(eventos(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------------------------------------
# Flashcards
# ------------------------------------------------------------------------------------------------


class PedidoFlashcards(BaseModel):
    foco: str | None = None


@router.post("/questoes/{questao_id}/flashcards/gerar")
async def gerar_flashcards(questao_id: str, dados: PedidoFlashcards):
    try:
        return {"cartoes": await tasks.gerar_flashcards(questao_id, dados.foco)}
    except ErroClaude as exc:
        raise HTTPException(502, str(exc)) from exc


class Cartao(BaseModel):
    frente: str = Field(min_length=1)
    verso: str = Field(min_length=1)
    questao_id: str | None = None
    origem: str = "llm"


class NovosCartoes(BaseModel):
    cartoes: list[Cartao]


@router.post("/flashcards")
def salvar_flashcards(dados: NovosCartoes):
    ids = []
    with conectar() as conn:
        for c in dados.cartoes:
            tema = None
            if c.questao_id:
                q = linha(conn, "SELECT tema_id FROM questoes WHERE id = ?", (c.questao_id,))
                tema = q["tema_id"] if q else None
            fsrs_json, due = srs.novo_cartao()
            cur = conn.execute(
                "INSERT INTO flashcards (questao_id, tema_id, frente, verso, origem, fsrs_json, due) VALUES (?,?,?,?,?,?,?)",
                (c.questao_id, tema, c.frente.strip(), c.verso.strip(),
                 c.origem if c.origem in ("llm", "manual", "coach", "tutor") else "manual", fsrs_json, due),
            )
            ids.append(cur.lastrowid)
    return {"ids": ids}


@router.get("/flashcards")
def listar_flashcards(vencidos: bool = False, limite: int = 200, tema_id: str | None = None,
                      questao_id: str | None = None):
    sql = ["SELECT f.*, t.nome AS tema_nome FROM flashcards f LEFT JOIN temas t ON t.id = f.tema_id WHERE 1=1"]
    params: list = []
    if vencidos:
        sql.append("AND f.suspenso = 0 AND f.due <= ?")
        params.append(datetime.now(UTC).isoformat())
    if tema_id:
        sql.append("AND f.tema_id = ?")
        params.append(tema_id)
    if questao_id:
        sql.append("AND f.questao_id = ?")
        params.append(questao_id)
    sql.append("ORDER BY f.due LIMIT ?" if vencidos else "ORDER BY f.id DESC LIMIT ?")
    params.append(limite)
    with conectar() as conn:
        cards = linhas(conn, " ".join(sql), params)
        total = linha(conn, "SELECT COUNT(*) AS n FROM flashcards WHERE suspenso = 0")["n"]
    for c in cards:
        estado = json.loads(c.pop("fsrs_json"))
        c["estado"] = {k: estado.get(k) for k in ("state", "stability", "difficulty", "last_review")}
    return {"cartoes": cards, "total_ativos": total}


class Revisao(BaseModel):
    nota: int = Field(ge=1, le=4)


@router.post("/flashcards/{card_id}/revisar")
def revisar_flashcard(card_id: int, dados: Revisao):
    with conectar() as conn:
        c = obter_ou_404(conn, "SELECT * FROM flashcards WHERE id = ?", (card_id,), "flashcard")
        fsrs_json, due = srs.revisar(c["fsrs_json"], dados.nota, config.dias_ate_prova())
        conn.execute("UPDATE flashcards SET fsrs_json = ?, due = ? WHERE id = ?", (fsrs_json, due, card_id))
        conn.execute("INSERT INTO revisoes (flashcard_id, nota) VALUES (?, ?)", (card_id, dados.nota))
    return {"due": due}


class EdicaoCartao(BaseModel):
    frente: str | None = None
    verso: str | None = None
    suspenso: bool | None = None


@router.patch("/flashcards/{card_id}")
def editar_flashcard(card_id: int, dados: EdicaoCartao):
    with conectar() as conn:
        obter_ou_404(conn, "SELECT id FROM flashcards WHERE id = ?", (card_id,), "flashcard")
        if dados.frente is not None:
            conn.execute("UPDATE flashcards SET frente = ? WHERE id = ?", (dados.frente, card_id))
        if dados.verso is not None:
            conn.execute("UPDATE flashcards SET verso = ? WHERE id = ?", (dados.verso, card_id))
        if dados.suspenso is not None:
            conn.execute("UPDATE flashcards SET suspenso = ? WHERE id = ?", (int(dados.suspenso), card_id))
    return {"ok": True}


@router.delete("/flashcards/{card_id}")
def apagar_flashcard(card_id: int):
    with conectar() as conn:
        conn.execute("DELETE FROM flashcards WHERE id = ?", (card_id,))
    return {"ok": True}


# ------------------------------------------------------------------------------------------------
# Ajustes, perfil e uso
# ------------------------------------------------------------------------------------------------


@router.get("/ajustes")
def obter_ajustes():
    with conectar() as conn:
        return {"ajustes": ajustes.todos(conn), "modelos_disponiveis": ajustes.MODELOS_DISPONIVEIS,
                "perfil": config.carregar_perfil()}


@router.put("/ajustes")
def salvar_ajustes(novos: dict):
    with conectar() as conn:
        try:
            return {"ajustes": ajustes.atualizar(conn, novos)}
        except KeyError as exc:
            raise HTTPException(422, f"ajuste desconhecido: {exc}") from exc


@router.put("/perfil")
def salvar_perfil(perfil: dict):
    atual = config.carregar_perfil()
    atual.update({k: v for k, v in perfil.items() if k in config.PERFIL_PADRAO})
    config.salvar_perfil(atual)
    return atual


@router.get("/uso")
def uso():
    with conectar() as conn:
        return {
            "hoje": tasks.jobs_hoje(conn),
            "limite": linha(conn, "SELECT * FROM limite_uso WHERE id = 1"),
            "recentes": linhas(conn, "SELECT id, papel, modelo, status, fundo, input_tokens + output_tokens + "
                                     "cache_read + cache_write AS tokens, custo_usd, duracao_ms, erro, criado_em "
                                     "FROM llm_jobs ORDER BY id DESC LIMIT 30"),
            "fundo_hoje": sentinela.gasto_fundo_hoje(conn),
            "orcamento_fundo_dia": ajustes.obter(conn, "orcamento_fundo_dia"),
            "aviso_tokens_dia": ajustes.obter(conn, "aviso_tokens_dia"),
        }
