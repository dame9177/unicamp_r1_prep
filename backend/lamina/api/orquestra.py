"""Rotas do Preceptor e da orquestração: estado, rondas, conversas, agenda, avisos, tarefas e cadernos."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from lamina import agentes
from lamina.api.comum import obter_ou_404
from lamina.claude.tools import TIPOS_AGENDA, desfazer
from lamina.db import conectar, linha, linhas, salvar_estado
from lamina.orquestra import progresso, sentinela
from lamina.orquestra.maestro import maestro

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------------------------------------
# Preceptor
# ------------------------------------------------------------------------------------------------


@router.get("/preceptor")
def estado():
    with conectar() as conn:
        return {
            "maestro": maestro.estado(),
            "sinais": sentinela.coletar(conn),
            "rondas": linhas(conn, "SELECT * FROM coach_insights WHERE tipo = 'analise' ORDER BY id DESC LIMIT 15"),
            "acoes": linhas(conn, "SELECT * FROM coach_acoes ORDER BY id DESC LIMIT 60"),
            "insights": linhas(conn, "SELECT * FROM coach_insights WHERE tipo != 'analise' ORDER BY id DESC LIMIT 40"),
            "chats": linhas(conn, """
                SELECT c.id, c.atualizado_em,
                       (SELECT conteudo FROM mensagens m WHERE m.chat_id = c.id AND m.papel = 'user'
                        ORDER BY m.id LIMIT 1) AS titulo
                FROM chats c WHERE c.agente = 'preceptor' ORDER BY c.atualizado_em DESC LIMIT 30"""),
        }


class PedidoRonda(BaseModel):
    observacao: str | None = None


@router.post("/preceptor/ronda")
async def ronda(dados: PedidoRonda):  # async: o trabalho vira uma tarefa no event loop
    if not maestro.disparar_ronda("pedido do aluno", fundo=False, pedido_extra=dados.observacao):
        raise HTTPException(409, f"o Preceptor está ocupado: {maestro.ocupado}")
    return {"iniciado": True}


class Pausa(BaseModel):
    horas: float = Field(ge=0, le=24 * 14)


@router.post("/preceptor/pausa")
def pausar(dados: Pausa):
    ate = (datetime.now(UTC) + timedelta(hours=dados.horas)).isoformat() if dados.horas else None
    with conectar() as conn:
        salvar_estado(conn, "pausa_fundo_ate", ate)
    return {"pausado_ate": ate}


@router.post("/preceptor/chats")
def novo_chat():
    from lamina.api.ia import _chat_completo

    with conectar() as conn:
        cur = conn.execute("INSERT INTO chats (questao_id, agente) VALUES (NULL, 'preceptor')")
        return _chat_completo(conn, linha(conn, "SELECT * FROM chats WHERE id = ?", (cur.lastrowid,)))


@router.post("/preceptor/acoes/{acao_id}/desfazer")
def desfazer_acao(acao_id: int):
    with conectar() as conn:
        if not desfazer(conn, acao_id):
            raise HTTPException(404, "ação inexistente ou já desfeita")
    return {"ok": True}


@router.post("/preceptor/missoes/{missao_id}/feita")
def marcar_missao(missao_id: int, feita: bool = True):
    with conectar() as conn:
        m = obter_ou_404(conn, "SELECT * FROM coach_insights WHERE id = ? AND tipo = 'missao'", (missao_id,), "missão")
        payload = {**json.loads(m["payload_json"] or "{}"), "feita": feita}
        conn.execute("UPDATE coach_insights SET payload_json = ? WHERE id = ?", (json.dumps(payload), missao_id))
    return {"ok": True}


@router.patch("/preceptor/insights/{insight_id}")
def arquivar_insight(insight_id: int, arquivado: bool = True):
    with conectar() as conn:
        conn.execute("UPDATE coach_insights SET arquivado = ? WHERE id = ?", (int(arquivado), insight_id))
    return {"ok": True}


# ------------------------------------------------------------------------------------------------
# Agenda
# ------------------------------------------------------------------------------------------------


@router.get("/agenda")
def agenda(de: str | None = None, ate: str | None = None):
    de = de or (date.today() - timedelta(days=7)).isoformat()
    ate = ate or (date.today() + timedelta(days=21)).isoformat()
    with conectar() as conn:
        progresso.sincronizar(conn)
        return linhas(conn, """SELECT a.*, t.nome AS tema_nome, b.nome AS bloco_nome FROM agenda a
                               LEFT JOIN temas t ON t.id = a.tema_id LEFT JOIN blocos b ON b.id = a.bloco_id
                               WHERE a.dia BETWEEN ? AND ? ORDER BY a.dia, a.id""", (de, ate))


class ItemAgenda(BaseModel):
    dia: date
    titulo: str = Field(min_length=1, max_length=200)
    tipo: str = "estudo"
    detalhe: str | None = None
    tema_id: str | None = None
    bloco_id: int | None = None
    minutos: int | None = None


@router.post("/agenda")
def criar_item(item: ItemAgenda):
    if item.tipo not in TIPOS_AGENDA:
        raise HTTPException(422, f"tipo deve ser um de {TIPOS_AGENDA}")
    with conectar() as conn:
        cur = conn.execute("INSERT INTO agenda (dia, titulo, tipo, detalhe, tema_id, bloco_id, minutos, origem) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, 'aluno')",
                           (item.dia.isoformat(), item.titulo, item.tipo, item.detalhe, item.tema_id, item.bloco_id,
                            item.minutos))
        return linha(conn, "SELECT * FROM agenda WHERE id = ?", (cur.lastrowid,))


class EdicaoAgenda(BaseModel):
    status: str | None = None
    dia: date | None = None
    titulo: str | None = None
    detalhe: str | None = None


@router.patch("/agenda/{item_id}")
def editar_item(item_id: int, dados: EdicaoAgenda):
    campos = dados.model_dump(exclude_unset=True)
    if "status" in campos and campos["status"] not in ("planejado", "feito", "pulado"):
        raise HTTPException(422, "status inválido")
    with conectar() as conn:
        obter_ou_404(conn, "SELECT id FROM agenda WHERE id = ?", (item_id,), "item")
        for k, v in campos.items():
            conn.execute(f"UPDATE agenda SET {k} = ? WHERE id = ?", (v.isoformat() if k == "dia" else v, item_id))
        return linha(conn, "SELECT * FROM agenda WHERE id = ?", (item_id,))


@router.delete("/agenda/{item_id}")
def apagar_item(item_id: int):
    with conectar() as conn:
        conn.execute("DELETE FROM agenda WHERE id = ?", (item_id,))
    return {"ok": True}


# ------------------------------------------------------------------------------------------------
# Avisos
# ------------------------------------------------------------------------------------------------


@router.get("/avisos")
def avisos(todos: bool = False):
    with conectar() as conn:
        filtro = "status IN ('entregue', 'lido')" if todos else "status = 'entregue'"
        return {
            "itens": linhas(conn, f"SELECT * FROM avisos WHERE {filtro} ORDER BY COALESCE(entregue_em, quando) DESC "
                                  "LIMIT 50"),
            "nao_lidos": linha(conn, "SELECT COUNT(*) AS n FROM avisos WHERE status = 'entregue'")["n"],
            "agendados": linhas(conn, "SELECT * FROM avisos WHERE status = 'agendado' ORDER BY quando LIMIT 20"),
            "maestro": {"ocupado": maestro.ocupado, "ativo": maestro.estado()["ativo"]},
        }


@router.post("/avisos/lidos")
def marcar_todos_lidos():
    with conectar() as conn:
        conn.execute("UPDATE avisos SET status = 'lido' WHERE status = 'entregue'")
    return {"ok": True}


@router.post("/avisos/{aviso_id}/{acao}")
def acao_aviso(aviso_id: int, acao: str):
    novo = {"lido": "lido", "descartar": "descartado"}.get(acao)
    if not novo:
        raise HTTPException(404, "ação desconhecida")
    with conectar() as conn:
        conn.execute("UPDATE avisos SET status = ? WHERE id = ?", (novo, aviso_id))
    return {"ok": True}


# ------------------------------------------------------------------------------------------------
# Tarefas dos agentes
# ------------------------------------------------------------------------------------------------


@router.get("/tarefas")
def tarefas():
    with conectar() as conn:
        return linhas(conn, "SELECT * FROM tarefas ORDER BY (status NOT IN ('pendente', 'executando')), "
                            "prioridade, id DESC LIMIT 60")


class NovaTarefa(BaseModel):
    agente: str = "bibliotecario"
    titulo: str = Field(min_length=3, max_length=200)
    instrucoes: str = Field(min_length=3, max_length=4000)
    prioridade: int = Field(default=2, ge=1, le=3)


@router.post("/tarefas")
def criar_tarefa(dados: NovaTarefa):
    if dados.agente != "bibliotecario":
        raise HTTPException(422, "por ora só o bibliotecário recebe tarefas")
    with conectar() as conn:
        cur = conn.execute("INSERT INTO tarefas (agente, titulo, instrucoes, prioridade, criado_por) "
                           "VALUES (?, ?, ?, ?, 'aluno')", (dados.agente, dados.titulo, dados.instrucoes, dados.prioridade))
        return linha(conn, "SELECT * FROM tarefas WHERE id = ?", (cur.lastrowid,))


@router.post("/tarefas/{tarefa_id}/{acao}")
async def acao_tarefa(tarefa_id: int, acao: str):
    with conectar() as conn:
        t = obter_ou_404(conn, "SELECT * FROM tarefas WHERE id = ?", (tarefa_id,), "tarefa")
        if acao == "cancelar" and t["status"] == "pendente":
            conn.execute("UPDATE tarefas SET status = 'cancelada' WHERE id = ?", (tarefa_id,))
        elif acao == "repetir" and t["status"] in ("erro", "cancelada", "concluida"):
            conn.execute("UPDATE tarefas SET status = 'pendente', resultado = NULL WHERE id = ?", (tarefa_id,))
        elif acao == "executar" and t["status"] == "pendente":
            pass
        else:
            raise HTTPException(409, f"não é possível {acao} uma tarefa {t['status']}")
    if acao == "executar" and not maestro.disparar_tarefa(tarefa_id, fundo=False):
        raise HTTPException(409, f"há outro trabalho em andamento: {maestro.ocupado}")
    return {"ok": True}


# ------------------------------------------------------------------------------------------------
# Cadernos dos agentes (somente leitura para o aluno)
# ------------------------------------------------------------------------------------------------


@router.get("/agentes")
def listar_agentes():
    saida = []
    for nome, info in agentes.AGENTES.items():
        arquivos = agentes.listar_arquivos(nome)
        saida.append({"id": nome, **info, "arquivos": len(arquivos), "bytes": sum(a["bytes"] for a in arquivos)})
    return saida


@router.get("/agentes/{nome}/arquivos")
def arquivos_agente(nome: str):
    if nome not in agentes.AGENTES:
        raise HTTPException(404, "agente inexistente")
    return agentes.listar_arquivos(nome)


@router.get("/agentes/{nome}/arquivo")
def arquivo_agente(nome: str, caminho: str):
    if nome not in agentes.AGENTES:
        raise HTTPException(404, "agente inexistente")
    try:
        return {"caminho": caminho, "conteudo": agentes.ler_arquivo(nome, caminho)}
    except (PermissionError, FileNotFoundError) as exc:
        raise HTTPException(404, "arquivo não encontrado") from exc
