from decimal import Decimal

from eco_router.domain.models import (
    Currency,
    ModelSnapshot,
    Money,
    PricingSnapshot,
    QualityRating,
)

TASK_CLASS = "summarization"


def usd(amount: str) -> Money:
    return Money(Decimal(amount), Currency.USD)


def pricing(
    model_id: str,
    input_rate: str = "2",
    output_rate: str = "4",
) -> PricingSnapshot:
    return PricingSnapshot(
        snapshot_id=f"price-{model_id}-v1",
        model_id=model_id,
        currency=Currency.USD,
        input_per_million=Decimal(input_rate),
        output_per_million=Decimal(output_rate),
    )


def candidate(model_id: str, quality: int = 80) -> ModelSnapshot:
    return ModelSnapshot(
        model_id=model_id,
        capabilities=frozenset({"text"}),
        quality_ratings=(QualityRating(TASK_CLASS, quality, "demo-fixture"),),
        available=True,
        pricing=pricing(model_id),
        estimated_latency_ms=50,
        context_window_tokens=1_500,
        max_output_tokens=500,
    )
