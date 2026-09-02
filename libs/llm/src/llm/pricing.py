"""Локальная оценка стоимости вызова LLM.

Упрощение относительно FEATURES.md 3.9 (там эталон — OpenAI usage API по
проектам); для Блока 2 хватает приближённой локальной оценки по объявленным
ценам за токены — usage_events.cost ориентировочный, не биллинговый.
"""

from __future__ import annotations

from decimal import Decimal

# $ за 1M токенов (вход, выход). Обновлять при изменении цен OpenAI.
_PRICING_PER_MILLION_TOKENS: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
}
_UNKNOWN_MODEL_PRICE = (Decimal("0"), Decimal("0"))


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    price_in, price_out = _PRICING_PER_MILLION_TOKENS.get(model, _UNKNOWN_MODEL_PRICE)
    cost = (Decimal(tokens_in) * price_in + Decimal(tokens_out) * price_out) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"))
