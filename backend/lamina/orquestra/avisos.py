"""Avisos ao aluno: entrega (sino do app + notificação do desktop) e lembretes automáticos sem LLM."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, date, datetime

from lamina.db import linhas


def _agora_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def em_silencio(aj: dict, agora: datetime | None = None) -> bool:
    ini, fim = aj["silencio"]
    h = (agora or datetime.now()).hour
    if ini == fim:
        return False
    return (h >= ini or h < fim) if ini > fim else (ini <= h < fim)


def notificar_desktop(titulo: str, texto: str) -> bool:
    if not shutil.which("notify-send"):
        return False
    try:
        subprocess.Popen(["notify-send", "--app-name=Lâmina", "--icon=accessories-dictionary", titulo, texto[:300]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


notificador: Callable[[str, str], bool] = notificar_desktop  # substituível nos testes


def criar(conn, *, titulo: str, texto: str = "", tipo: str = "lembrete", link: str | None = None,
          origem: str = "sentinela", chave: str | None = None, quando: str | None = None) -> int | None:
    """Cria um aviso. Com `chave`, é idempotente (o mesmo lembrete não se repete)."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO avisos (tipo, titulo, texto, link, origem, chave, quando) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tipo, titulo, texto, link, origem, chave, quando or _agora_utc()))
    return cur.lastrowid if cur.rowcount else None


def entregar_pendentes(conn, aj: dict) -> int:
    if em_silencio(aj):
        return 0
    devidos = linhas(conn, "SELECT * FROM avisos WHERE status = 'agendado' AND quando <= ? ORDER BY quando LIMIT 5",
                     (_agora_utc(),))
    for a in devidos:
        conn.execute("UPDATE avisos SET status = 'entregue', entregue_em = ? WHERE id = ?", (_agora_utc(), a["id"]))
        if aj["notificacoes_desktop"]:
            notificador(a["titulo"], a["texto"])
    return len(devidos)


def lembretes_automaticos(conn, aj: dict, sinais: dict, agora: datetime | None = None) -> list[int]:
    """Lembretes óbvios, que não precisam de LLM. Cada um no máximo uma vez por dia."""
    agora = agora or datetime.now()
    if agora.hour < aj["hora_lembrete"] or sinais["dias_ate_prova"] < 0:
        return []
    hoje = date.today().isoformat()
    ids = []
    h = sinais["hoje"]
    if h["faltam"] > 0:
        ids.append(criar(conn, chave=f"meta:{hoje}", titulo="Meta do dia",
                         texto=f"Você respondeu {h['respondidas']} de {h['meta']} questões hoje. Faltam {h['faltam']}.",
                         link="/blocos"))
    if sinais["flashcards_vencidos"] >= 15:
        ids.append(criar(conn, chave=f"flashcards:{hoje}", titulo="Flashcards acumulados",
                         texto=f"{sinais['flashcards_vencidos']} cartões vencidos. Uma sessão curta resolve.",
                         link="/flashcards"))
    abertos = [i["titulo"] for i in sinais["agenda_hoje"] if i["status"] == "planejado"]
    if abertos:
        ids.append(criar(conn, chave=f"agenda:{hoje}", titulo="Agenda de hoje",
                         texto=f"{len(abertos)} item(ns) em aberto: " + "; ".join(abertos[:3]), link="/agenda"))
    return [i for i in ids if i]
