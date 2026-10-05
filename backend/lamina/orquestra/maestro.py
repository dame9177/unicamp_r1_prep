"""Maestro: o ciclo em segundo plano que acorda o Preceptor e executa a fila de tarefas dos agentes.

A cada `intervalo` segundos (sem gastar tokens):
  1. coleta os sinais (sentinela), cria lembretes óbvios e entrega avisos vencidos;
  2. se o segundo plano estiver liberado (ligado, dentro do orçamento e com folga na janela do plano):
     - roda uma ronda do Preceptor quando houver motivo (primeira do dia, muitas respostas novas);
     - senão, executa a próxima tarefa da fila (uma por vez).
Os trabalhos com LLM rodam como tarefas asyncio separadas, para o ciclo continuar entregando avisos.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from lamina import ajustes
from lamina.db import conectar, linha
from lamina.orquestra import avisos, sentinela

log = logging.getLogger("lamina.maestro")


LIMITE_FREIO = 0.95  # fração da janela do plano em que o trabalho de fundo em andamento é interrompido


def _horas_desde(iso: str | None) -> float:
    if not iso:
        return 1e9
    return (datetime.now(UTC) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() / 3600


def motivo_ronda(aj: dict, s: dict, agora: datetime | None = None) -> str | None:
    agora = agora or datetime.now()
    sp = s["segundo_plano"]
    if sp["rondas_hoje"] >= aj["max_rondas_dia"]:
        return None
    parado = (s["dias_sem_estudar"] or 0) >= 3
    if sp["rondas_hoje"] == 0 and agora.hour >= aj["hora_ronda"]:
        if parado and _horas_desde(s["ultima_ronda"]) < 48:
            return None  # aluno parado: não gasta tokens repetindo a mesma análise
        return "primeira ronda do dia: revisar o plano e organizar hoje"
    n = s["tentativas_desde_ultima_ronda"]
    if n >= aj["coach_min_tentativas_novas"] and _horas_desde(s["ultima_ronda"]) >= 3:
        return f"{n} respostas novas desde a última ronda"
    return None


def proxima_tarefa(conn) -> dict | None:
    return linha(conn, "SELECT * FROM tarefas WHERE status = 'pendente' ORDER BY prioridade, id LIMIT 1")


def recuperar_tarefas_presas(conn) -> None:
    """Tarefas que estavam 'executando' quando o servidor caiu voltam para a fila (até 3 tentativas)."""
    conn.execute("UPDATE tarefas SET status = 'erro', resultado = 'interrompida 3 vezes' "
                 "WHERE status = 'executando' AND tentativas >= 3")
    conn.execute("UPDATE tarefas SET status = 'pendente' WHERE status = 'executando'")


class Maestro:
    def __init__(self, intervalo: int = 300, atraso_inicial: int = 30):
        self.intervalo = intervalo
        self.atraso_inicial = atraso_inicial
        self.ocupado: str | None = None
        self.ultimo_tick: str | None = None
        self.ultima_decisao: str | None = None
        self.ultimo_erro: str | None = None
        self._ciclo_task: asyncio.Task | None = None
        self._job: asyncio.Task | None = None
        self._job_fundo = False

    # -- ciclo ---------------------------------------------------------------------------------

    def iniciar(self) -> None:
        with conectar() as conn:
            recuperar_tarefas_presas(conn)
        self._ciclo_task = asyncio.create_task(self._ciclo())

    async def parar(self) -> None:
        for t in (self._ciclo_task, self._job):
            if t and not t.done():
                t.cancel()
        self._ciclo_task = None

    async def _ciclo(self) -> None:
        await asyncio.sleep(self.atraso_inicial)
        while True:
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001 — o ciclo não pode morrer
                log.exception("falha no ciclo do maestro")
                self.ultimo_erro = str(exc)
            await asyncio.sleep(self.intervalo)

    async def tick(self) -> str:
        self.ultimo_tick = datetime.now(UTC).isoformat()
        with conectar() as conn:
            aj = ajustes.todos(conn)
            s = sentinela.coletar(conn)
            avisos.lembretes_automaticos(conn, aj, s)
            avisos.entregar_pendentes(conn, aj)
            tarefa = proxima_tarefa(conn)
        decisao = self._decidir(aj, s, tarefa)
        self.ultima_decisao = decisao
        return decisao

    def _janela_critica(self, s: dict) -> bool:
        j = s["segundo_plano"].get("janela") or {}
        return j.get("status") == "rejected" or (j.get("utilizacao") or 0) >= LIMITE_FREIO

    def _decidir(self, aj: dict, s: dict, tarefa: dict | None) -> str:
        if self.ocupado and self._job_fundo and self._janela_critica(s) and self._job and not self._job.done():
            # Freio de emergência: o trabalho de fundo não pode esgotar a janela do plano do aluno.
            self._job.cancel()
            return f"interrompido para poupar a janela do plano: {self.ocupado}"
        if self.ocupado:
            return f"ocupado: {self.ocupado}"
        if s["pausado_ate"] and s["pausado_ate"] > datetime.now(UTC).isoformat():
            return "pausado pelo aluno"
        sp = s["segundo_plano"]
        if not sp["pode_rodar"]:
            return f"aguardando: {sp['motivo']}"
        motivo = motivo_ronda(aj, s)
        if motivo:
            self.disparar_ronda(motivo, fundo=True)
            return f"ronda: {motivo}"
        if tarefa:
            self.disparar_tarefa(tarefa["id"], fundo=True)
            return f"tarefa #{tarefa['id']}: {tarefa['titulo']}"
        return "nada a fazer"

    # -- execução ------------------------------------------------------------------------------

    def _rodar(self, descricao: str, coro, fundo: bool) -> bool:
        if self.ocupado:
            coro.close()
            return False
        self.ocupado = descricao
        self._job_fundo = fundo

        async def envolver():
            try:
                await coro
                self.ultimo_erro = None
            except asyncio.CancelledError:
                self.ultimo_erro = f"{descricao}: interrompido"
            except Exception as exc:  # noqa: BLE001
                log.warning("%s falhou: %s", descricao, exc)
                self.ultimo_erro = f"{descricao}: {exc}"
            finally:
                self.ocupado = None

        self._job = asyncio.create_task(envolver())
        return True

    def disparar_ronda(self, motivo: str, fundo: bool = True, pedido_extra: str | None = None) -> bool:
        from lamina.claude import tasks

        return self._rodar(f"ronda ({motivo})", tasks.ronda_preceptor(motivo, pedido_extra=pedido_extra, fundo=fundo),
                           fundo)

    def disparar_tarefa(self, tarefa_id: int, fundo: bool = True) -> bool:
        from lamina.claude import tasks

        return self._rodar(f"tarefa #{tarefa_id}", tasks.executar_tarefa(tarefa_id, fundo=fundo), fundo)

    async def aguardar(self) -> None:
        if self._job:
            await asyncio.gather(self._job, return_exceptions=True)

    def estado(self) -> dict:
        return {"ativo": bool(self._ciclo_task and not self._ciclo_task.done()), "ocupado": self.ocupado,
                "ultimo_tick": self.ultimo_tick, "ultima_decisao": self.ultima_decisao,
                "ultimo_erro": self.ultimo_erro, "intervalo_seg": self.intervalo}


maestro = Maestro()
