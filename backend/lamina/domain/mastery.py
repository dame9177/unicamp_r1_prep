"""Regras de domínio de tema/bloco. Determinísticas, sem LLM.

- correto = 1, parcial = 0.5, incorreto = 0 (placar bruto).
- Acerto marcado como "chute" conta no placar bruto, mas vale 0 para domínio.
- Domínio usa a ÚLTIMA tentativa julgada de cada questão.
- Dominado: aproveitamento firme >= 80% com cobertura total (ou override manual).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

PONTOS = {"correto": 1.0, "parcial": 0.5, "incorreto": 0.0}
VEREDITOS_JULGADOS = tuple(PONTOS)
LIMIAR_DOMINIO = 0.8
DIAS_PARA_REVISAR = 14


def pontos_brutos(veredito: str) -> float:
    return PONTOS.get(veredito, 0.0)


def pontos_dominio(veredito: str, confianca: str) -> float:
    if confianca == "chute":
        return 0.0
    return PONTOS.get(veredito, 0.0)


@dataclass
class Estatistica:
    total: int = 0
    respondidas: int = 0
    pontos_brutos: float = 0.0
    pontos_dominio: float = 0.0
    corretas: int = 0
    parciais: int = 0
    incorretas: int = 0
    chutes: int = 0
    acertos_no_chute: int = 0
    ultima_atividade: str | None = None
    questoes_refazer: list[str] = field(default_factory=list)

    def adicionar(self, questao_id: str, veredito: str | None, confianca: str | None, quando: str | None) -> None:
        self.total += 1
        if veredito not in VEREDITOS_JULGADOS:
            return
        self.respondidas += 1
        self.pontos_brutos += pontos_brutos(veredito)
        self.pontos_dominio += pontos_dominio(veredito, confianca or "certeza")
        self.corretas += veredito == "correto"
        self.parciais += veredito == "parcial"
        self.incorretas += veredito == "incorreto"
        if confianca == "chute":
            self.chutes += 1
            self.acertos_no_chute += veredito == "correto"
        if veredito != "correto" or confianca == "chute":
            self.questoes_refazer.append(questao_id)
        if quando and (self.ultima_atividade is None or quando > self.ultima_atividade):
            self.ultima_atividade = quando

    @property
    def cobertura(self) -> float:
        return self.respondidas / self.total if self.total else 0.0

    @property
    def aproveitamento_bruto(self) -> float | None:
        return self.pontos_brutos / self.respondidas if self.respondidas else None

    @property
    def aproveitamento_firme(self) -> float | None:
        return self.pontos_dominio / self.respondidas if self.respondidas else None

    def status(self, status_manual: str | None = None) -> str:
        if status_manual == "dominado":
            return "dominado"
        if status_manual == "nao_dominado":
            return "em_progresso" if self.respondidas else "nao_iniciado"
        if self.respondidas == 0:
            return "nao_iniciado"
        firme = self.aproveitamento_firme or 0.0
        if self.respondidas == self.total and firme >= LIMIAR_DOMINIO - 1e-9:
            return "dominado"
        return "em_progresso"

    def precisa_revisar(self, status: str, agora: datetime | None = None) -> bool:
        if status != "dominado" or not self.ultima_atividade:
            return False
        agora = agora or datetime.now(UTC)
        ultima = datetime.fromisoformat(self.ultima_atividade.replace("Z", "+00:00"))
        return agora - ultima > timedelta(days=DIAS_PARA_REVISAR)

    def resumo(self, status_manual: str | None = None) -> dict:
        st = self.status(status_manual)
        return {
            "total": self.total,
            "respondidas": self.respondidas,
            "corretas": self.corretas,
            "parciais": self.parciais,
            "incorretas": self.incorretas,
            "chutes": self.chutes,
            "acertos_no_chute": self.acertos_no_chute,
            "cobertura": round(self.cobertura, 4),
            "aproveitamento_bruto": _arred(self.aproveitamento_bruto),
            "aproveitamento_firme": _arred(self.aproveitamento_firme),
            "status": st,
            "status_manual": status_manual,
            "revisar": self.precisa_revisar(st),
            "ultima_atividade": self.ultima_atividade,
            "n_refazer": len(self.questoes_refazer),
        }


def _arred(v: float | None) -> float | None:
    return None if v is None else round(v, 4)
