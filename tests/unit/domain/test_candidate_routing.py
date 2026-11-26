from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from eco_router.domain.models import (
    CatalogSnapshot,
    DomainValidationError,
    QualityRating,
    TokenUsage,
)
from eco_router.domain.services.routing import (
    CandidateTokenBounds,
    ExcludedCandidate,
    ExclusionReason,
    RoutingConstraints,
    RoutingPolicy,
    rank_candidates,
)

from .test_domain_data import TASK_CLASS, candidate, pricing, usd


@pytest.fixture
def usage() -> TokenUsage:
    return TokenUsage(input_tokens=1_000, output_tokens=500)


@pytest.fixture
def constraints() -> RoutingConstraints:
    return RoutingConstraints(
        task_class=TASK_CLASS,
        minimum_quality=80,
        required_capabilities=frozenset({"text"}),
        max_attempt_cost=usd("0.004"),
        max_estimated_latency_ms=50,
    )


@pytest.fixture
def policy() -> RoutingPolicy:
    return RoutingPolicy(
        version="policy-v1",
        quality_weight=1,
        cost_weight=1,
        latency_weight=1,
        cost_scale_usd=Decimal("0.008"),
        latency_scale_ms=100,
    )


@pytest.mark.parametrize(
    ("changes", "bounds_usage", "reason"),
    [
        pytest.param(
            {"available": False},
            TokenUsage(1_000, 500),
            ExclusionReason.UNAVAILABLE,
            id="unavailable",
        ),
        pytest.param(
            {"available": None},
            TokenUsage(1_000, 500),
            ExclusionReason.UNAVAILABLE,
            id="unknown-availability",
        ),
        pytest.param(
            {"capabilities": frozenset()},
            TokenUsage(1_000, 500),
            ExclusionReason.MISSING_CAPABILITY,
            id="missing-capability",
        ),
        pytest.param(
            {"quality_ratings": (QualityRating("other-task", 100, "fixture"),)},
            TokenUsage(1_000, 500),
            ExclusionReason.MISSING_QUALITY,
            id="quality-for-different-task",
        ),
        pytest.param(
            {"quality_ratings": (QualityRating(TASK_CLASS, 79, "fixture"),)},
            TokenUsage(1_000, 500),
            ExclusionReason.BELOW_QUALITY_FLOOR,
            id="one-below-quality-floor",
        ),
        pytest.param(
            {},
            None,
            ExclusionReason.MISSING_TOKEN_BOUNDS,
            id="missing-token-bounds",
        ),
        pytest.param(
            {"context_window_tokens": None},
            TokenUsage(1_000, 500),
            ExclusionReason.MISSING_MODEL_LIMIT,
            id="unknown-context",
        ),
        pytest.param(
            {"max_output_tokens": None},
            TokenUsage(1_000, 500),
            ExclusionReason.MISSING_MODEL_LIMIT,
            id="unknown-output-limit",
        ),
        pytest.param(
            {"context_window_tokens": 1_499},
            TokenUsage(1_000, 500),
            ExclusionReason.CONTEXT_WINDOW_EXCEEDED,
            id="one-over-context",
        ),
        pytest.param(
            {"max_output_tokens": 499},
            TokenUsage(1_000, 500),
            ExclusionReason.OUTPUT_LIMIT_EXCEEDED,
            id="one-over-output-limit",
        ),
        pytest.param(
            {"pricing": None},
            TokenUsage(1_000, 500),
            ExclusionReason.MISSING_PRICE,
            id="missing-price",
        ),
        pytest.param(
            {"pricing": pricing("alpha", input_rate="2.001")},
            TokenUsage(1_000, 500),
            ExclusionReason.ABOVE_COST_LIMIT,
            id="over-cost-limit",
        ),
        pytest.param(
            {"estimated_latency_ms": None},
            TokenUsage(1_000, 500),
            ExclusionReason.MISSING_LATENCY,
            id="unknown-latency",
        ),
        pytest.param(
            {"estimated_latency_ms": 51},
            TokenUsage(1_000, 500),
            ExclusionReason.ABOVE_LATENCY_LIMIT,
            id="one-over-latency-limit",
        ),
    ],
)
def test_each_hard_constraint_excludes_candidate(
    changes: dict[str, Any],
    bounds_usage: TokenUsage | None,
    reason: ExclusionReason,
    constraints: RoutingConstraints,
    policy: RoutingPolicy,
) -> None:
    model = replace(candidate("alpha"), **changes)
    bounds = (
        () if bounds_usage is None else (CandidateTokenBounds("alpha", bounds_usage),)
    )

    result = rank_candidates(
        constraints, CatalogSnapshot("catalog-v1", (model,)), bounds, policy
    )

    assert result.ranked == ()
    assert result.excluded == (ExcludedCandidate("alpha", reason),)


def test_candidate_at_all_hard_limits_is_eligible(
    constraints: RoutingConstraints,
    policy: RoutingPolicy,
    usage: TokenUsage,
) -> None:
    result = rank_candidates(
        constraints,
        CatalogSnapshot("catalog-v1", (candidate("alpha"),)),
        (CandidateTokenBounds("alpha", usage),),
        policy,
    )

    assert result.catalog_snapshot_id == "catalog-v1"
    assert result.policy_version == "policy-v1"
    assert result.constraints == constraints
    assert result.excluded == ()
    (ranked,) = result.ranked
    assert ranked.model_id == "alpha"
    assert ranked.pricing_snapshot_id == "price-alpha-v1"
    assert ranked.maximum_usage == usage
    assert ranked.estimated_maximum_cost == usd("0.004")
    assert ranked.estimated_latency_ms == 50
    assert ranked.quality_score == 80
    # Equal weights for utilities 0.80, 0.50 and 0.50 give 0.60.
    assert ranked.score_basis_points == 6_000


def test_low_quality_candidate_is_excluded_even_when_cost_would_rank_it_first(
    constraints: RoutingConstraints,
    policy: RoutingPolicy,
    usage: TokenUsage,
) -> None:
    cheap = replace(
        candidate("cheap", quality=79),
        pricing=pricing("cheap", input_rate="0", output_rate="0"),
    )
    models = (cheap, candidate("beta"), candidate("alpha"))
    cost_only = replace(policy, quality_weight=0, latency_weight=0)

    result = rank_candidates(
        constraints,
        CatalogSnapshot("catalog-v1", models),
        tuple(CandidateTokenBounds(model.model_id, usage) for model in models),
        cost_only,
    )

    assert tuple(item.model_id for item in result.ranked) == ("alpha", "beta")
    assert result.excluded == (
        ExcludedCandidate("cheap", ExclusionReason.BELOW_QUALITY_FLOOR),
    )


def test_ranking_orders_by_score_then_breaks_ties_by_model_id(
    constraints: RoutingConstraints,
    policy: RoutingPolicy,
    usage: TokenUsage,
) -> None:
    models = (candidate("beta"), candidate("zeta", 90), candidate("alpha"))
    bounds = tuple(CandidateTokenBounds(model.model_id, usage) for model in models)
    quality_only = replace(policy, cost_weight=0, latency_weight=0)

    first = rank_candidates(
        constraints, CatalogSnapshot("catalog-v1", models), bounds, quality_only
    )
    permuted = rank_candidates(
        constraints,
        CatalogSnapshot("catalog-v1", tuple(reversed(models))),
        bounds[1:] + bounds[:1],
        quality_only,
    )

    assert tuple((item.model_id, item.score_basis_points) for item in first.ranked) == (
        ("zeta", 9_000),
        ("alpha", 8_000),
        ("beta", 8_000),
    )
    assert permuted == first


def test_empty_catalog_returns_empty_routing_result(
    constraints: RoutingConstraints,
    policy: RoutingPolicy,
) -> None:
    result = rank_candidates(constraints, CatalogSnapshot("empty", ()), (), policy)

    assert result.ranked == ()
    assert result.excluded == ()


@pytest.mark.parametrize(
    "model_ids",
    [("alpha", "alpha"), ("unknown",)],
    ids=["duplicate-bounds", "unknown-model"],
)
def test_ranking_rejects_inconsistent_token_bounds(
    model_ids: tuple[str, ...],
    constraints: RoutingConstraints,
    policy: RoutingPolicy,
    usage: TokenUsage,
) -> None:
    bounds = tuple(CandidateTokenBounds(model_id, usage) for model_id in model_ids)
    with pytest.raises(DomainValidationError):
        rank_candidates(
            constraints,
            CatalogSnapshot("catalog-v1", (candidate("alpha"),)),
            bounds,
            policy,
        )


def test_candidate_token_bounds_require_positive_output_capacity() -> None:
    with pytest.raises(DomainValidationError):
        CandidateTokenBounds("alpha", TokenUsage(1_000, 0))


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"minimum_quality": 101}, id="quality-over-100"),
        pytest.param({"max_attempt_cost": usd("-0.001")}, id="negative-cost-cap"),
        pytest.param({"max_estimated_latency_ms": -1}, id="negative-latency-cap"),
    ],
)
def test_routing_constraints_reject_invalid_limits(
    constraints: RoutingConstraints,
    changes: dict[str, Any],
) -> None:
    with pytest.raises(DomainValidationError):
        replace(constraints, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param(
            {"quality_weight": 0, "cost_weight": 0, "latency_weight": 0},
            id="all-zero-weights",
        ),
        pytest.param({"cost_weight": -1}, id="negative-weight"),
        pytest.param({"cost_scale_usd": Decimal("0")}, id="zero-cost-scale"),
        pytest.param({"latency_scale_ms": 0}, id="zero-latency-scale"),
    ],
)
def test_routing_policy_rejects_invalid_configuration(
    policy: RoutingPolicy,
    changes: dict[str, Any],
) -> None:
    with pytest.raises(DomainValidationError):
        replace(policy, **changes)
