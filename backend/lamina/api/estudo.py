"""Temas, blocos, simulado e painel."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lamina import ajustes, config, consultas
from lamina.api.comum import em_segundo_plano, obter_ou_404
from lamina.claude import tasks
from lamina.db import conectar, linha, linhas
from lamina.domain import blocks
from lamina.orquestra import progresso

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------------------------------------
# Temas
# ------------------------------------------------------------------------------------------------


@router.get("/temas")
def listar_temas():
    with conectar() as conn:
        return consultas.estatisticas_temas(conn)


@router.get("/temas/{tema_id}")
def obter_tema(tema_id: str):
    with conectar() as conn:
        tema = next((t for t in consultas.estatisticas_temas(conn) if t["id"] == tema_id), None)
        if not tema:
            raise HTTPException(404, "tema não encontrado")
        ult = {r["questao_id"]: r for r in consultas.ultimas_tentativas(conn)}
        qs = linhas(conn, """SELECT id, prova_id, processo, numero, subtopico, tipo_cognitivo, formato_original,
                                    adaptada, imagens_json != '[]' AS tem_imagem, substr(enunciado, -180) AS trecho
                             FROM questoes WHERE tema_id = ? AND anulada = 0
                             ORDER BY processo DESC, prova_id, numero""", (tema_id,))
        for q in qs:
            u = ult.get(q["id"])
            q["ultimo_veredito"] = u["veredito"] if u else None
            q["ultima_confianca"] = u["confianca"] if u else None
        blocos_tema = linhas(conn, "SELECT id, nome, tipo, criado_em, finalizado_em FROM blocos "
                                   "WHERE tema_id = ? AND arquivado = 0 ORDER BY id DESC LIMIT 10", (tema_id,))
        return {"tema": tema, "questoes": qs, "blocos": blocos_tema}


class StatusTema(BaseModel):
    status_manual: Literal["dominado", "nao_dominado"] | None


@router.patch("/temas/{tema_id}")
def marcar_tema(tema_id: str, dados: StatusTema):
    with conectar() as conn:
        obter_ou_404(conn, "SELECT id FROM temas WHERE id = ?", (tema_id,), "tema")
        conn.execute(
            "UPDATE temas SET status_manual = ?, status_manual_em = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (dados.status_manual, tema_id),
        )
    return {"ok": True}


# ------------------------------------------------------------------------------------------------
# Blocos
# ------------------------------------------------------------------------------------------------


class NovoBloco(BaseModel):
    tipo: Literal["tema", "refazer", "custom", "simulado", "area", "imagens"]
    nome: str | None = None
    tema_id: str | None = None
    area: str | None = None
    bloco_origem_id: int | None = None
    questao_ids: list[str] | None = None
    modo: Literal["todas", "ineditas"] = "todas"
    limite: int | None = None
    duracao_min: int | None = None


def _ineditas(conn, ids: list[str]) -> list[str]:
    feitas = {r["questao_id"] for r in linhas(conn, "SELECT DISTINCT questao_id FROM tentativas")}
    return [i for i in ids if i not in feitas]


@router.post("/blocos")
def criar_bloco(dados: NovoBloco):
    with conectar() as conn:
        tema_id = dados.tema_id
        cfg: dict = {}
        if dados.tipo == "tema":
            tema = obter_ou_404(conn, "SELECT * FROM temas WHERE id = ?", (dados.tema_id,), "tema")
            ids = blocks.ordenar_nao_respondidas_primeiro(conn, blocks.questoes_do_tema(conn, tema["id"]))
            nome = dados.nome or tema["nome"]
        elif dados.tipo == "area":
            if dados.area not in config.AREAS:
                raise HTTPException(422, "área inválida")
            ids = [r["id"] for r in linhas(conn, "SELECT id FROM questoes WHERE area = ? AND anulada = 0 "
                                                 "ORDER BY processo DESC", (dados.area,))]
            ids = blocks.ordenar_nao_respondidas_primeiro(conn, ids)
            nome = dados.nome or dados.area
        elif dados.tipo == "imagens":
            sql = "SELECT id FROM questoes WHERE imagens_json != '[]' AND anulada = 0"
            params: tuple = ()
            if dados.area:
                sql += " AND area = ?"
                params = (dados.area,)
            ids = [r["id"] for r in linhas(conn, sql + " ORDER BY processo DESC", params)]
            ids = blocks.ordenar_nao_respondidas_primeiro(conn, ids)
            nome = dados.nome or ("Imagens" + (f" · {dados.area}" if dados.area else ""))
        elif dados.tipo == "refazer":
            if dados.bloco_origem_id:
                origem = blocks.ids_do_bloco(conn, dados.bloco_origem_id)
                b = obter_ou_404(conn, "SELECT * FROM blocos WHERE id = ?", (dados.bloco_origem_id,), "bloco")
                nome = dados.nome or f"Refazer · {b['nome']}"
                tema_id = b["tema_id"]
            elif dados.tema_id:
                tema = obter_ou_404(conn, "SELECT * FROM temas WHERE id = ?", (dados.tema_id,), "tema")
                origem = blocks.questoes_do_tema(conn, tema["id"])
                nome = dados.nome or f"Refazer · {tema['nome']}"
            else:
                raise HTTPException(422, "informe bloco_origem_id ou tema_id")
            ids = blocks.refazer_ids(conn, origem)
        elif dados.tipo == "simulado":
            ids = blocks.selecionar_simulado(conn)
            n = linha(conn, "SELECT COUNT(*) AS n FROM blocos WHERE tipo = 'simulado'")["n"] + 1
            nome = dados.nome or f"Simulado {n}"
            cfg = {"duracao_min": dados.duracao_min or ajustes.obter(conn, "simulado_duracao_min")}
        else:
            ids = dados.questao_ids or []
            nome = dados.nome or "Bloco personalizado"

        if dados.modo == "ineditas" and dados.tipo != "refazer":
            ids = _ineditas(conn, ids)
        if dados.limite:
            ids = ids[: dados.limite]
        if not ids:
            raise HTTPException(422, "nenhuma questão para este bloco")
        bid = blocks.criar_bloco(conn, nome, dados.tipo if dados.tipo not in ("area", "imagens") else "custom", ids,
                                 tema_id=tema_id, config_bloco=cfg)
        return {"id": bid, "n": len(ids)}


def _progresso_bloco(conn, bloco_id: int, ids: list[str]) -> dict:
    feitas = linhas(conn, """
        SELECT questao_id, veredito, confianca FROM (
          SELECT t.*, ROW_NUMBER() OVER (PARTITION BY questao_id ORDER BY id DESC) AS rn
          FROM tentativas t WHERE bloco_id = ?) WHERE rn = 1""", (bloco_id,))
    por_q = {f["questao_id"]: f for f in feitas}
    return {"respondidas": len(por_q), "total": len(ids), "por_questao": por_q}


@router.get("/blocos")
def listar_blocos(incluir_arquivados: bool = False):
    with conectar() as conn:
        bs = linhas(conn, "SELECT * FROM blocos WHERE arquivado = 0 OR ? ORDER BY id DESC LIMIT 100",
                    (int(incluir_arquivados),))
        for b in bs:
            ids = blocks.ids_do_bloco(conn, b["id"])
            prog = _progresso_bloco(conn, b["id"], ids)
            b["total"] = prog["total"]
            b["respondidas"] = prog["respondidas"]
            b["estatistica"] = consultas.estatistica_de(conn, ids)
            b["estatistica_no_bloco"] = _estat_no_bloco(prog["por_questao"])
            b["config"] = json.loads(b.pop("config_json") or "{}")
        return bs


@router.get("/blocos/{bloco_id}")
def obter_bloco(bloco_id: int):
    with conectar() as conn:
        b = obter_ou_404(conn, "SELECT * FROM blocos WHERE id = ?", (bloco_id,), "bloco")
        ids = blocks.ids_do_bloco(conn, bloco_id)
        prog = _progresso_bloco(conn, bloco_id, ids)
        simulado_aberto = b["tipo"] == "simulado" and not b["finalizado_em"]
        info = {r["id"]: r for r in linhas(
            conn, f"SELECT id, area, tema_id, processo, numero FROM questoes WHERE id IN ({','.join('?' * len(ids))})",
            ids)} if ids else {}
        questoes = []
        for i, qid in enumerate(ids):
            f = prog["por_questao"].get(qid)
            questoes.append({
                "id": qid, "ordem": i, "area": info[qid]["area"], "processo": info[qid]["processo"],
                "respondida": bool(f),
                "veredito": (None if simulado_aberto else (f["veredito"] if f else None)),
                "confianca": f["confianca"] if f else None,
            })
        b["config"] = json.loads(b.pop("config_json") or "{}")
        return {
            "bloco": b,
            "questoes": questoes,
            "respondidas": prog["respondidas"],
            "estatistica": None if simulado_aberto else consultas.estatistica_de(conn, ids),
            "estatistica_no_bloco": None if simulado_aberto else _estat_no_bloco(prog["por_questao"]),
        }


def _estat_no_bloco(por_q: dict) -> dict:
    from lamina.domain.mastery import Estatistica

    est = Estatistica()
    for qid, f in por_q.items():
        est.adicionar(qid, f["veredito"], f["confianca"], None)
    return est.resumo()


@router.post("/blocos/{bloco_id}/finalizar")
async def finalizar_bloco(bloco_id: int):
    with conectar() as conn:
        b = obter_ou_404(conn, "SELECT * FROM blocos WHERE id = ?", (bloco_id,), "bloco")
        conn.execute("UPDATE blocos SET finalizado_em = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (bloco_id,))
        pendentes = [r["id"] for r in linhas(
            conn, "SELECT id FROM tentativas WHERE bloco_id = ? AND veredito IN ('pendente', 'erro')", (bloco_id,))]
    if pendentes and b["tipo"] == "simulado":
        em_segundo_plano(tasks.julgar_lote(pendentes))
    return {"ok": True, "julgando": len(pendentes) if b["tipo"] == "simulado" else 0}


@router.delete("/blocos/{bloco_id}")
def arquivar_bloco(bloco_id: int):
    with conectar() as conn:
        conn.execute("UPDATE blocos SET arquivado = 1 WHERE id = ?", (bloco_id,))
    return {"ok": True}


# ------------------------------------------------------------------------------------------------
# Painel
# ------------------------------------------------------------------------------------------------


@router.get("/painel")
def painel():
    with conectar() as conn:
        progresso.sincronizar(conn)
        temas = consultas.estatisticas_temas(conn)
        nao_dominados = [t for t in temas if t["status"] != "dominado"]
        prioritarios = sorted(nao_dominados, key=lambda t: -t["prioridade"])[:3]
        revisar = [t for t in temas if t["revisar"]][:3]
        perfil = config.carregar_perfil()
        ult = tasks.ultima_analise(conn)
        aj = ajustes.todos(conn)
        novas = tasks.tentativas_desde_ultima_analise(conn)
        return {
            "dias_ate_prova": config.dias_ate_prova(),
            "data_prova": perfil["data_prova"],
            "nome": perfil.get("nome") or "",
            "totais": consultas.totais(conn),
            "areas": consultas.estatisticas_areas(conn),
            "prioritarios": prioritarios,
            "revisar": revisar,
            "mapa": [{k: t[k] for k in ("id", "nome", "area", "status", "aproveitamento_firme", "cobertura",
                                         "revisar", "prioridade", "total", "respondidas", "geral")} for t in temas],
            "flashcards_vencidos": consultas.flashcards_vencidos(conn),
            "missoes": [{**m, "feita": progresso.missao_feita(conn, m)} for m in linhas(
                conn, "SELECT * FROM coach_insights WHERE tipo = 'missao' AND arquivado = 0 ORDER BY id")],
            "insights": linhas(conn, "SELECT * FROM coach_insights WHERE tipo IN ('insight', 'alerta') "
                                     "AND arquivado = 0 ORDER BY id DESC LIMIT 4"),
            "ultima_analise": ult,
            "meta_diaria": aj["meta_diaria"],
            "coach_sugerido": novas >= aj["coach_min_tentativas_novas"],
            "tentativas_desde_analise": novas,
            "serie": consultas.serie_diaria(conn, 21),
            "agenda_hoje": linhas(conn, """SELECT a.id, a.titulo, a.tipo, a.detalhe, a.status, a.tema_id, a.bloco_id,
                                                  a.minutos, t.nome AS tema_nome FROM agenda a
                                           LEFT JOIN temas t ON t.id = a.tema_id
                                           WHERE a.dia = date('now', 'localtime') ORDER BY a.id"""),
            "blocos_abertos": linhas(conn, """
                SELECT b.id, b.nome, b.tipo, b.criado_por,
                       (SELECT COUNT(*) FROM bloco_questoes bq WHERE bq.bloco_id = b.id) AS total,
                       (SELECT COUNT(DISTINCT questao_id) FROM tentativas t WHERE t.bloco_id = b.id) AS respondidas
                FROM blocos b WHERE b.arquivado = 0 AND b.finalizado_em IS NULL ORDER BY b.id DESC LIMIT 5"""),
        }


# ------------------------------------------------------------------------------------------------
# Busca local (sem tokens)
# ------------------------------------------------------------------------------------------------


@router.get("/busca")
def buscar(q: str, area: str | None = None, limite: int = 60):
    termos = [t for t in q.strip().split() if len(t) > 1]
    if not termos:
        return []
    sql = ["""SELECT q.id, q.area, q.processo, q.numero, q.tema_id, t.nome AS tema_nome, q.subtopico,
                     q.imagens_json != '[]' AS tem_imagem, substr(q.enunciado, -200) AS trecho
              FROM questoes q LEFT JOIN temas t ON t.id = q.tema_id WHERE q.anulada = 0"""]
    params: list = []
    for termo in termos:
        sql.append("AND (q.enunciado LIKE ? OR IFNULL(q.enunciado_compartilhado, '') LIKE ? OR "
                   "IFNULL(q.resposta_esperada, '') LIKE ? OR IFNULL(q.subtopico, '') LIKE ? OR IFNULL(t.nome, '') LIKE ?)")
        params += [f"%{termo}%"] * 5
    if area:
        sql.append("AND q.area = ?")
        params.append(area)
    sql.append("ORDER BY q.processo DESC LIMIT ?")
    params.append(min(limite, 200))
    with conectar() as conn:
        rows = linhas(conn, " ".join(sql), params)
        ult = {r["questao_id"]: r for r in consultas.ultimas_tentativas(conn)}
    for r in rows:
        u = ult.get(r["id"])
        r["ultimo_veredito"] = u["veredito"] if u else None
    return rows
