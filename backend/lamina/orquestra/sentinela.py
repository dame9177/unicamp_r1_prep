"""Sentinela: sinais objetivos do estudo e do orçamento, calculados sem LLM (custo zero).

O Preceptor só é acordado quando os sinais justificam; os lembretes óbvios (meta do dia, flashcards
acumulados) saem daqui mesmo, sem gastar tokens.
"""

from __future__ import annotations

import time
from datetime import date, datetime

from lamina import ajustes, config, consultas
from lamina.db import linha, linhas, obter_estado


def _hoje_local() -> str:
    return date.today().isoformat()


# Tokens "efetivos": leituras de cache custam ~1/10 de um token de entrada (no preço da API e, por
# aproximação, no consumo do plano). Sem esse peso, uma ronda (~130k de cache) pareceria 3× mais cara.
TOKENS_EFETIVOS = "(input_tokens + output_tokens + cache_write + cache_read / 10)"


def gasto_fundo_hoje(conn) -> int:
    r = linha(conn, f"""SELECT COALESCE(SUM({TOKENS_EFETIVOS}), 0) AS n FROM llm_jobs
                        WHERE fundo = 1 AND date(criado_em, 'localtime') = date('now', 'localtime')""")
    return int(r["n"])


def janela(conn) -> dict | None:
    return linha(conn, "SELECT status, utilizacao, reseta_em, tipo, atualizado_em FROM limite_uso WHERE id = 1")


def pode_rodar_fundo(conn, aj: dict | None = None) -> tuple[bool, str]:
    """O segundo plano só roda se estiver ligado, dentro do orçamento e com folga na janela do plano."""
    aj = aj or ajustes.todos(conn)
    if not aj["preceptor_fundo"]:
        return False, "segundo plano desligado nos ajustes"
    gasto = gasto_fundo_hoje(conn)
    if gasto >= aj["orcamento_fundo_dia"]:
        return False, f"orçamento do dia esgotado ({gasto // 1000}k de {aj['orcamento_fundo_dia'] // 1000}k tokens)"
    j = janela(conn)
    if j and j["reseta_em"] and j["reseta_em"] > time.time():
        if j["status"] == "rejected":
            return False, "janela do plano esgotada"
        if j["utilizacao"] is not None and j["utilizacao"] >= aj["limiar_janela"]:
            return False, f"janela do plano em {round(j['utilizacao'] * 100)}%"
        if j["status"] == "allowed_warning" and j["utilizacao"] is None:
            return False, "janela do plano perto do limite"
    return True, "ok"


def ultima_ronda(conn) -> dict | None:
    return linha(conn, "SELECT id, criado_em FROM coach_insights WHERE tipo = 'analise' ORDER BY id DESC LIMIT 1")


def rondas_hoje(conn) -> int:
    return linha(conn, """SELECT COUNT(*) AS n FROM coach_insights WHERE tipo = 'analise'
                          AND date(criado_em, 'localtime') = date('now', 'localtime')""")["n"]


def coletar(conn) -> dict:
    aj = ajustes.todos(conn)
    hoje = _hoje_local()
    respondidas_hoje = linha(conn, "SELECT COUNT(*) AS n FROM tentativas "
                                   "WHERE date(criado_em, 'localtime') = date('now', 'localtime')")["n"]
    ult = linha(conn, "SELECT MAX(criado_em) AS t FROM tentativas")["t"]
    dias_sem = None
    if ult:
        dias_sem = (date.today() - datetime.fromisoformat(ult.replace("Z", "+00:00")).astimezone().date()).days
    ronda = ultima_ronda(conn)
    desde = ronda["criado_em"] if ronda else "1970-01-01"
    temas = consultas.estatisticas_temas(conn)
    revisar = [t["nome"] for t in sorted(temas, key=lambda t: -t["prioridade"]) if t["revisar"]]
    ok, motivo = pode_rodar_fundo(conn, aj)
    bib = linha(conn, "SELECT COALESCE(SUM(tipo = 'documento'), 0) AS d, COALESCE(SUM(tipo = 'nota'), 0) AS n "
                      "FROM biblioteca")
    return {
        "agora": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dias_ate_prova": config.dias_ate_prova(),
        "hoje": {"respondidas": respondidas_hoje, "meta": aj["meta_diaria"],
                 "faltam": max(0, aj["meta_diaria"] - respondidas_hoje)},
        "dias_sem_estudar": dias_sem,
        "flashcards_vencidos": consultas.flashcards_vencidos(conn),
        "agenda_hoje": linhas(conn, "SELECT id, titulo, tipo, status FROM agenda WHERE dia = ? ORDER BY id", (hoje,)),
        "temas_a_revisar": {"n": len(revisar), "principais": revisar[:5]},
        "ultima_ronda": ronda["criado_em"] if ronda else None,
        "tentativas_desde_ultima_ronda": linha(conn, "SELECT COUNT(*) AS n FROM tentativas WHERE criado_em > ?",
                                               (desde,))["n"],
        "tarefas": linha(conn, """SELECT COALESCE(SUM(status = 'pendente'), 0) AS pendentes,
                                         COALESCE(SUM(status = 'executando'), 0) AS executando,
                                         COALESCE(SUM(status = 'erro' AND concluido_em > datetime('now', '-1 day')), 0)
                                           AS erros_24h FROM tarefas"""),
        "avisos_nao_lidos": linha(conn, "SELECT COUNT(*) AS n FROM avisos WHERE status = 'entregue'")["n"],
        "biblioteca": {"documentos": bib["d"], "notas": bib["n"]},
        "segundo_plano": {"pode_rodar": ok, "motivo": motivo, "gasto_hoje": gasto_fundo_hoje(conn),
                          "orcamento": aj["orcamento_fundo_dia"], "janela": janela(conn),
                          "rondas_hoje": rondas_hoje(conn)},
        "pausado_ate": obter_estado(conn, "pausa_fundo_ate"),
    }
