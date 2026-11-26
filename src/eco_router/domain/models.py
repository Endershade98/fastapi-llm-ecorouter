from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class DomainValidationError(ValueError):
    """Raised when a value violates a domain invariant."""


class Currency(StrEnum):
    USD = "USD"


def require_identifier(value: str, field: str) -> None:
    if not value or value != value.strip():
        raise DomainValidationError(f"{field} must be nonempty and trimmed")


def require_non_negative_int(value: int, field: str) -> None:
    if isinstance(value, bool) or value < 0:
        raise DomainValidationError(f"{field} must be a nonnegative integer")


def require_non_negative_decimal(value: Decimal, field: str) -> None:
    if not value.is_finite() or value < 0:
        raise DomainValidationError(f"{field} must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if not self.amount.is_finite():
            raise DomainValidationError("money amount must be finite")
        if self.currency is not Currency.USD:
            raise DomainValidationError("only USD is supported")


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        require_non_negative_int(self.input_tokens, "input_tokens")
        require_non_negative_int(self.output_tokens, "output_tokens")


@dataclass(frozen=True, slots=True)
class PricingSnapshot:
    snapshot_id: str
    model_id: str
    currency: Currency
    input_per_million: Decimal
    output_per_million: Decimal

    def __post_init__(self) -> None:
        require_identifier(self.snapshot_id, "pricing snapshot ID")
        require_identifier(self.model_id, "pricing model ID")
        if self.currency is not Currency.USD:
            raise DomainValidationError("only USD is supported")
        require_non_negative_decimal(self.input_per_million, "input_per_million")
        require_non_negative_decimal(self.output_per_million, "output_per_million")


@dataclass(frozen=True, slots=True)
class QualityRating:
    task_class: str
    score: int
    evidence_ref: str

    def __post_init__(self) -> None:
        require_identifier(self.task_class, "quality task class")
        require_identifier(self.evidence_ref, "quality evidence reference")
        require_non_negative_int(self.score, "quality score")
        if self.score > 100:
            raise DomainValidationError("quality score must be at most 100")


@dataclass(frozen=True, slots=True)
class ModelSnapshot:
    model_id: str
    capabilities: frozenset[str]
    quality_ratings: tuple[QualityRating, ...]
    available: bool | None
    pricing: PricingSnapshot | None
    estimated_latency_ms: int | None
    context_window_tokens: int | None
    max_output_tokens: int | None

    def __post_init__(self) -> None:
        require_identifier(self.model_id, "model ID")
        for capability in self.capabilities:
            require_identifier(capability, "capability")
        task_classes = {rating.task_class for rating in self.quality_ratings}
        if len(task_classes) != len(self.quality_ratings):
            raise DomainValidationError("duplicate task class in quality ratings")
        if self.pricing is not None and self.pricing.model_id != self.model_id:
            raise DomainValidationError("pricing snapshot belongs to another model")

        limits = (
            ("estimated_latency_ms", self.estimated_latency_ms),
            ("context_window_tokens", self.context_window_tokens),
            ("max_output_tokens", self.max_output_tokens),
        )
        for field, value in limits:
            if value is not None:
                require_non_negative_int(value, field)

    def quality_for(self, task_class: str) -> QualityRating | None:
        return next(
            (
                rating
                for rating in self.quality_ratings
                if rating.task_class == task_class
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    snapshot_id: str
    models: tuple[ModelSnapshot, ...]

    def __post_init__(self) -> None:
        require_identifier(self.snapshot_id, "catalog snapshot ID")
        model_ids = {model.model_id for model in self.models}
        if len(model_ids) != len(self.models):
            raise DomainValidationError("duplicate model ID in catalog")
