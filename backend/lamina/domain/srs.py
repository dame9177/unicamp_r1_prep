"""Repetição espaçada com FSRS, com intervalo máximo limitado pela data da prova."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fsrs import Card, Rating, Scheduler

NOTAS = {1: Rating.Again, 2: Rating.Hard, 3: Rating.Good, 4: Rating.Easy}


def agendador(dias_ate_prova: int) -> Scheduler:
    # Nada deve "sumir" para depois da prova: o intervalo máximo acompanha a contagem regressiva.
    return Scheduler(desired_retention=0.9, maximum_interval=max(1, min(60, dias_ate_prova - 1)))


def novo_cartao() -> tuple[str, str]:
    c = Card()
    return json.dumps(c.to_dict()), c.due.isoformat()


def revisar(fsrs_json: str, nota: int, dias_ate_prova: int, agora: datetime | None = None) -> tuple[str, str]:
    if nota not in NOTAS:
        raise ValueError("nota deve ser 1..4")
    cartao = Card.from_dict(json.loads(fsrs_json))
    novo, _ = agendador(dias_ate_prova).review_card(cartao, NOTAS[nota], agora or datetime.now(UTC))
    return json.dumps(novo.to_dict()), novo.due.isoformat()
