from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from typing import Any

import pytest

from eco_router.domain.models import (
    CatalogSnapshot,
    Currency,
    DomainValidationError,
    Money,
    QualityRating,
    TokenUsage,
)

from .test_domain_data import TASK_CLASS, candidate, pricing


@pytest.mark.parametrize(
    ("input_tokens", "output_tokens"),
    [(-1, 0), (0, -1), (True, 0), (0, False)],
)
def test_token_usage_rejects_negative_values_and_booleans(
    input_tokens: int,
    output_tokens: int,
) -> None:
    with pytest.raises(DomainValidationError):
        TokenUsage(input_tokens, output_tokens)


def test_token_usage_accepts_zero_and_is_immutable() -> None:
    usage = TokenUsage(0, 0)
    assert (usage.input_tokens, usage.output_tokens) == (0, 0)

    with pytest.raises(FrozenInstanceError):
        usage.input_tokens = 1  # type: ignore[misc]


@pytest.mark.parametrize("amount", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_money_rejects_non_finite_amounts(amount: str) -> None:
    with pytest.raises(DomainValidationError):
        Money(Decimal(amount), Currency.USD)


@pytest.mark.parametrize("rate", ["-0.1", "NaN", "Infinity"])
@pytest.mark.parametrize("field", ["input_per_million", "output_per_million"])
def test_pricing_rejects_invalid_rates(field: str, rate: str) -> None:
    with pytest.raises(DomainValidationError):
        replace(pricing("alpha"), **{field: Decimal(rate)})


@pytest.mark.parametrize("score", [0, 100])
def test_quality_rating_accepts_boundary_scores(score: int) -> None:
    assert QualityRating(TASK_CLASS, score, "fixture").score == score


@pytest.mark.parametrize("score", [-1, 101, True])
def test_quality_rating_rejects_invalid_scores(score: int) -> None:
    with pytest.raises(DomainValidationError):
        QualityRating(TASK_CLASS, score, "fixture")


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"model_id": " alpha"}, id="untrimmed-id"),
        pytest.param({"capabilities": frozenset({""})}, id="empty-capability"),
        pytest.param({"pricing": pricing("beta")}, id="foreign-pricing"),
        pytest.param({"estimated_latency_ms": -1}, id="negative-latency"),
        pytest.param({"context_window_tokens": -1}, id="negative-context"),
        pytest.param({"max_output_tokens": -1}, id="negative-output-limit"),
        pytest.param(
            {
                "quality_ratings": (
                    QualityRating(TASK_CLASS, 80, "first"),
                    QualityRating(TASK_CLASS, 90, "second"),
                ),
            },
            id="duplicate-task-class",
        ),
    ],
)
def test_model_snapshot_rejects_inconsistent_data(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(DomainValidationError):
        replace(candidate("alpha"), **changes)


def test_catalog_rejects_duplicate_model_ids() -> None:
    with pytest.raises(DomainValidationError):
        CatalogSnapshot("catalog-v1", (candidate("alpha"), candidate("alpha", 90)))
