from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction

from eco_router.domain.models import (
    CatalogSnapshot,
    DomainValidationError,
    ModelSnapshot,
    Money,
    TokenUsage,
    require_identifier,
    require_non_negative_decimal,
    require_non_negative_int,
)
from eco_router.domain.services.accounting import price_usage


class ExclusionReason(StrEnum):
    UNAVAILABLE = "unavailable"
    MISSING_CAPABILITY = "missing_capability"
    MISSING_QUALITY = "missing_quality"
    BELOW_QUALITY_FLOOR = "below_quality_floor"
    MISSING_TOKEN_BOUNDS = "missing_token_bounds"
    MISSING_MODEL_LIMIT = "missing_model_limit"
    CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
    MISSING_PRICE = "missing_price"
    ABOVE_COST_LIMIT = "above_cost_limit"
    MISSING_LATENCY = "missing_latency"
    ABOVE_LATENCY_LIMIT = "above_latency_limit"


@dataclass(frozen=True, slots=True)
class RoutingConstraints:
    task_class: str
    minimum_quality: int
    required_capabilities: frozenset[str]
    max_attempt_cost: Money
    max_estimated_latency_ms: int

    def __post_init__(self) -> None:
        require_identifier(self.task_class, "routing task class")
        require_non_negative_int(self.minimum_quality, "minimum_quality")
        if self.minimum_quality > 100:
            raise DomainValidationError("minimum_quality must be at most 100")
        for capability in self.required_capabilities:
            require_identifier(capability, "required capability")
        require_non_negative_decimal(self.max_attempt_cost.amount, "max_attempt_cost")
        require_non_negative_int(
            self.max_estimated_latency_ms, "max_estimated_latency_ms"
        )


@dataclass(frozen=True, slots=True)
class CandidateTokenBounds:
    model_id: str
    maximum_usage: TokenUsage

    def __post_init__(self) -> None:
        require_identifier(self.model_id, "token bounds model ID")
        if self.maximum_usage.output_tokens == 0:
            raise DomainValidationError("output token bound must be positive")


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    version: str
    quality_weight: int
    cost_weight: int
    latency_weight: int
    cost_scale_usd: Decimal
    latency_scale_ms: int

    def __post_init__(self) -> None:
        require_identifier(self.version, "routing policy version")
        weights = (
            ("quality_weight", self.quality_weight),
            ("cost_weight", self.cost_weight),
            ("latency_weight", self.latency_weight),
        )
        for field, weight in weights:
            require_non_negative_int(weight, field)
        if self.total_weight == 0:
            raise DomainValidationError("at least one weight must be positive")
        require_non_negative_decimal(self.cost_scale_usd, "cost_scale_usd")
        require_non_negative_int(self.latency_scale_ms, "latency_scale_ms")
        if self.cost_scale_usd == 0 or self.latency_scale_ms == 0:
            raise DomainValidationError("normalization scales must be positive")

    @property
    def total_weight(self) -> int:
        return self.quality_weight + self.cost_weight + self.latency_weight


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    model_id: str
    pricing_snapshot_id: str
    quality_score: int
    maximum_usage: TokenUsage
    estimated_maximum_cost: Money
    estimated_latency_ms: int
    score_basis_points: int


@dataclass(frozen=True, slots=True)
class ExcludedCandidate:
    model_id: str
    reason: ExclusionReason


@dataclass(frozen=True, slots=True)
class RoutingResult:
    catalog_snapshot_id: str
    policy_version: str
    constraints: RoutingConstraints
    ranked: tuple[RankedCandidate, ...]
    excluded: tuple[ExcludedCandidate, ...]


def rank_candidates(
    constraints: RoutingConstraints,
    catalog: CatalogSnapshot,
    token_bounds: tuple[CandidateTokenBounds, ...],
    policy: RoutingPolicy,
) -> RoutingResult:
    """Return eligible candidates in primary and strict fallback order."""
    bounds_by_model = {entry.model_id: entry.maximum_usage for entry in token_bounds}
    if len(bounds_by_model) != len(token_bounds):
        raise DomainValidationError("duplicate model ID in token bounds")
    if bounds_by_model.keys() - {model.model_id for model in catalog.models}:
        raise DomainValidationError("token bounds refer to an unknown model")

    ranked: list[RankedCandidate] = []
    excluded: list[ExcludedCandidate] = []
    for model in catalog.models:
        candidate = _evaluate(
            model, bounds_by_model.get(model.model_id), constraints, policy
        )
        if isinstance(candidate, RankedCandidate):
            ranked.append(candidate)
        else:
            excluded.append(candidate)

    return RoutingResult(
        catalog_snapshot_id=catalog.snapshot_id,
        policy_version=policy.version,
        constraints=constraints,
        ranked=tuple(
            sorted(ranked, key=lambda item: (-item.score_basis_points, item.model_id))
        ),
        excluded=tuple(sorted(excluded, key=lambda item: item.model_id)),
    )


def _evaluate(
    model: ModelSnapshot,
    usage: TokenUsage | None,
    constraints: RoutingConstraints,
    policy: RoutingPolicy,
) -> RankedCandidate | ExcludedCandidate:
    model_id = model.model_id
    if model.available is not True:
        return ExcludedCandidate(model_id, ExclusionReason.UNAVAILABLE)
    if not constraints.required_capabilities <= model.capabilities:
        return ExcludedCandidate(model_id, ExclusionReason.MISSING_CAPABILITY)

    quality = model.quality_for(constraints.task_class)
    if quality is None:
        return ExcludedCandidate(model_id, ExclusionReason.MISSING_QUALITY)
    if quality.score < constraints.minimum_quality:
        return ExcludedCandidate(model_id, ExclusionReason.BELOW_QUALITY_FLOOR)

    if usage is None:
        return ExcludedCandidate(model_id, ExclusionReason.MISSING_TOKEN_BOUNDS)
    context_window = model.context_window_tokens
    output_limit = model.max_output_tokens
    if context_window is None or output_limit is None:
        return ExcludedCandidate(model_id, ExclusionReason.MISSING_MODEL_LIMIT)
    if usage.output_tokens > output_limit:
        return ExcludedCandidate(model_id, ExclusionReason.OUTPUT_LIMIT_EXCEEDED)
    if usage.input_tokens + usage.output_tokens > context_window:
        return ExcludedCandidate(model_id, ExclusionReason.CONTEXT_WINDOW_EXCEEDED)

    pricing = model.pricing
    if pricing is None:
        return ExcludedCandidate(model_id, ExclusionReason.MISSING_PRICE)
    maximum_cost = price_usage(pricing, usage)
    if maximum_cost.amount > constraints.max_attempt_cost.amount:
        return ExcludedCandidate(model_id, ExclusionReason.ABOVE_COST_LIMIT)

    latency = model.estimated_latency_ms
    if latency is None:
        return ExcludedCandidate(model_id, ExclusionReason.MISSING_LATENCY)
    if latency > constraints.max_estimated_latency_ms:
        return ExcludedCandidate(model_id, ExclusionReason.ABOVE_LATENCY_LIMIT)

    return RankedCandidate(
        model_id=model_id,
        pricing_snapshot_id=pricing.snapshot_id,
        quality_score=quality.score,
        maximum_usage=usage,
        estimated_maximum_cost=maximum_cost,
        estimated_latency_ms=latency,
        score_basis_points=_score(quality.score, maximum_cost.amount, latency, policy),
    )


def _score(
    quality: int,
    cost_usd: Decimal,
    latency_ms: int,
    policy: RoutingPolicy,
) -> int:
    one = Fraction(1)
    quality_utility = Fraction(quality, 100)
    cost_ratio = Fraction(cost_usd) / Fraction(policy.cost_scale_usd)
    latency_ratio = Fraction(latency_ms, policy.latency_scale_ms)
    cost_utility = one - min(one, cost_ratio)
    latency_utility = one - min(one, latency_ratio)

    weighted = (
        policy.quality_weight * quality_utility
        + policy.cost_weight * cost_utility
        + policy.latency_weight * latency_utility
    )
    return round(weighted * 10_000 / policy.total_weight)
