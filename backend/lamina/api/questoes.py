"""Questões, tentativas (respostas) e correção."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from lamina import ajustes
from lamina.api.comum import (
    em_segundo_plano,
    gabarito,
    obter_ou_404,
    questao_publica,
    resumo_tentativa,
    valores_referencia,
)
from lamina.claude import tasks
from lamina.db import conectar, linha, linhas

router = APIRouter(prefix="/api")


@router.get("/questoes/{questao_id}")
def obter_questao(questao_id: str, revelar: bool = False, bloco_id: int | None = None):
    with conectar() as conn:
        q = obter_ou_404(conn, "SELECT * FROM questoes WHERE id = ?", (questao_id,), "questão")
        ja_respondida = linha(conn, "SELECT 1 FROM tentativas WHERE questao_id = ? LIMIT 1", (questao_id,))
        if bloco_id is not None:
            # Dentro de um bloco, o gabarito só aparece depois de responder NESTE bloco
            # (e, no simulado, só depois de finalizar).
            b = linha(conn, "SELECT tipo, finalizado_em FROM blocos WHERE id = ?", (bloco_id,))
            no_bloco = linha(conn, "SELECT 1 FROM tentativas WHERE questao_id = ? AND bloco_id = ?", (questao_id, bloco_id))
            simulado_aberto = b and b["tipo"] == "simulado" and not b["finalizado_em"]
            revelar = revelar or (bool(no_bloco) and not simulado_aberto)
        else:
            revelar = revelar or bool(ja_respondida)
        return questao_publica(conn, q, revelar)


@router.get("/questoes/{questao_id}/tentativas")
def historico(questao_id: str):
    with conectar() as conn:
        return [resumo_tentativa(t) for t in linhas(
            conn, "SELECT * FROM tentativas WHERE questao_id = ? ORDER BY id DESC", (questao_id,))]


@router.get("/provas/{prova_id}/valores-referencia")
def valores(prova_id: str):
    return {"markdown": valores_referencia(prova_id)}


class NovaTentativa(BaseModel):
    questao_id: str
    resposta: str = Field(min_length=1, max_length=4000)
    confianca: Literal["certeza", "duvida", "chute"]
    bloco_id: int | None = None
    tempo_seg: int | None = None


@router.post("/tentativas")
async def responder(dados: NovaTentativa):
    with conectar() as conn:
        q = obter_ou_404(conn, "SELECT * FROM questoes WHERE id = ?", (dados.questao_id,), "questão")
        simulado = False
        if dados.bloco_id is not None:
            b = obter_ou_404(conn, "SELECT * FROM blocos WHERE id = ?", (dados.bloco_id,), "bloco")
            simulado = b["tipo"] == "simulado" and not b["finalizado_em"]
            if not b["iniciado_em"]:
                conn.execute("UPDATE blocos SET iniciado_em = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                             (b["id"],))
        cur = conn.execute(
            "INSERT INTO tentativas (questao_id, bloco_id, resposta, confianca, tempo_seg) VALUES (?, ?, ?, ?, ?)",
            (q["id"], dados.bloco_id, dados.resposta.strip(), dados.confianca, dados.tempo_seg),
        )
        tid = cur.lastrowid
        auto = ajustes.obter(conn, "correcao_automatica")
        t = linha(conn, "SELECT * FROM tentativas WHERE id = ?", (tid,))
    if auto and not simulado:
        em_segundo_plano(tasks.julgar_tentativa(tid))
    return {
        "tentativa": resumo_tentativa(t),
        "gabarito": None if simulado else gabarito(q),
        "julgando": bool(auto and not simulado),
    }


@router.get("/tentativas/{tentativa_id}")
def obter_tentativa(tentativa_id: int):
    with conectar() as conn:
        return resumo_tentativa(obter_ou_404(conn, "SELECT * FROM tentativas WHERE id = ?", (tentativa_id,), "tentativa"))


class VereditoManual(BaseModel):
    veredito: Literal["correto", "parcial", "incorreto"]
    confianca: Literal["certeza", "duvida", "chute"] | None = None


@router.patch("/tentativas/{tentativa_id}")
def corrigir_manual(tentativa_id: int, dados: VereditoManual):
    with conectar() as conn:
        obter_ou_404(conn, "SELECT id FROM tentativas WHERE id = ?", (tentativa_id,), "tentativa")
        conn.execute(
            """UPDATE tentativas SET veredito = ?, fonte_veredito = 'manual', confianca = COALESCE(?, confianca),
                 julgado_em = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
            (dados.veredito, dados.confianca, tentativa_id),
        )
        return resumo_tentativa(linha(conn, "SELECT * FROM tentativas WHERE id = ?", (tentativa_id,)))


class Rejulgar(BaseModel):
    revisao: bool = True


@router.post("/tentativas/{tentativa_id}/rejulgar")
async def rejulgar(tentativa_id: int, dados: Rejulgar):
    with conectar() as conn:
        t = obter_ou_404(conn, "SELECT * FROM tentativas WHERE id = ?", (tentativa_id,), "tentativa")
        if t["bloco_id"]:
            b = linha(conn, "SELECT tipo, finalizado_em FROM blocos WHERE id = ?", (t["bloco_id"],))
            if b and b["tipo"] == "simulado" and not b["finalizado_em"]:
                raise HTTPException(409, "finalize o simulado antes de corrigir")
        conn.execute("UPDATE tentativas SET veredito = 'pendente' WHERE id = ?", (tentativa_id,))
    em_segundo_plano(tasks.julgar_tentativa(tentativa_id, revisao=dados.revisao))
    return {"julgando": True}


class Explicacao(BaseModel):
    mensagem_id: int | None = None
    texto: str | None = None


@router.put("/questoes/{questao_id}/explicacao")
def fixar_explicacao(questao_id: str, dados: Explicacao):
    with conectar() as conn:
        texto = dados.texto
        if dados.mensagem_id is not None:
            m = obter_ou_404(conn, "SELECT conteudo FROM mensagens WHERE id = ?", (dados.mensagem_id,), "mensagem")
            texto = m["conteudo"]
        if not texto:
            raise HTTPException(422, "explicação vazia")
        conn.execute(
            """INSERT INTO questao_notas (questao_id, explicacao_md, fixada_em)
               VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
               ON CONFLICT(questao_id) DO UPDATE SET explicacao_md = excluded.explicacao_md, fixada_em = excluded.fixada_em""",
            (questao_id, texto),
        )
    return {"ok": True}


@router.delete("/questoes/{questao_id}/explicacao")
def remover_explicacao(questao_id: str):
    with conectar() as conn:
        conn.execute("DELETE FROM questao_notas WHERE questao_id = ?", (questao_id,))
    return {"ok": True}
