"""Локальная оценка стоимости вызова LLM."""

from __future__ import annotations

from decimal import Decimal

from llm.pricing import compute_cost


def test_computes_cost_for_known_model() -> None:
    # gpt-4o-mini: $0.15/1M вход, $0.60/1M выход
    cost = compute_cost("gpt-4o-mini", tokens_in=1_000_000, tokens_out=1_000_000)
    assert cost == Decimal("0.75")


def test_zero_tokens_is_zero_cost() -> None:
    assert compute_cost("gpt-4o-mini", 0, 0) == Decimal("0")


def test_unknown_model_defaults_to_zero_cost() -> None:
    assert compute_cost("some-future-model", 1000, 1000) == Decimal("0")


def test_input_and_output_priced_independently() -> None:
    only_input = compute_cost("gpt-4o", tokens_in=1_000_000, tokens_out=0)
    only_output = compute_cost("gpt-4o", tokens_in=0, tokens_out=1_000_000)
    assert only_input == Decimal("2.5")
    assert only_output == Decimal("10")
