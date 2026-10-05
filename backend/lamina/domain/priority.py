"""Prioridade de estudo por tema: prevalência na banca × lacuna de domínio × peso do coach."""

from __future__ import annotations

BASE_LACUNA = 0.35


def lacuna(aproveitamento_firme: float | None) -> float:
    if aproveitamento_firme is None:
        return 1.0
    return max(0.0, min(1.0, 1.0 - aproveitamento_firme))


def prioridade(prevalencia_norm: float, aproveitamento_firme: float | None, peso_coach: float = 1.0) -> float:
    return prevalencia_norm * (BASE_LACUNA + (1 - BASE_LACUNA) * lacuna(aproveitamento_firme)) * peso_coach


def normalizar(valores: dict[str, float]) -> dict[str, float]:
    maior = max(valores.values(), default=0.0)
    if maior <= 0:
        return {k: 0.0 for k in valores}
    return {k: v / maior for k, v in valores.items()}
