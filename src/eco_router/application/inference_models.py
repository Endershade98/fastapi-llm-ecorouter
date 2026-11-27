from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from eco_router.domain.models import (
    CatalogSnapshot,
    Money,
    TokenUsage,
    require_identifier,
    require_non_negative_decimal,
    require_non_negative_int,
)
from eco_router.domain.services.accounting import (
    AttemptUsage,
    Baseline,
    ExecutionAccounting,
    ExecutionMode,
    UsageSource,
)
from eco_router.domain.services.routing import (
    CandidateTokenBounds,
    RankedCandidate,
    RoutingConstraints,
    RoutingPolicy,
    RoutingResult,
)


class ApplicationError(RuntimeError):
    """Base error for application operations."""


class InvalidExecutionPlan(ApplicationError):
    """Raised when an inference plan has inconsistent inputs."""


class AttemptAccountingError(ApplicationError):
    """Raised when the durable lifecycle of an attempt cannot be confirmed."""


class ProviderContractError(ApplicationError):
    """Raised when an adapter returns an inconsistent outcome."""


class ProviderOutcomeKind(StrEnum):
    SUCCEEDED = "succeeded"
    TRANSIENT_REJECTED = "transient_rejected"
    PERMANENT_FAILURE = "permanent_failure"
    AMBIGUOUS_FAILURE = "ambiguous_failure"


class ExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    NO_ELIGIBLE_MODEL = "no_eligible_model"
    NO_ADMISSIBLE_ATTEMPT = "no_admissible_attempt"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    tenant_id: str
    execution_id: str
    mode: ExecutionMode

    def __post_init__(self) -> None:
        require_identifier(self.tenant_id, "tenant ID")
        require_identifier(self.execution_id, "execution ID")


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    max_tokens: int
    max_cost: Money
    deadline: float
    attempt_timeout_seconds: float

    def __post_init__(self) -> None:
        require_non_negative_int(self.max_tokens, "execution token limit")
        require_non_negative_decimal(self.max_cost.amount, "execution cost limit")
        if not isfinite(self.deadline):
            raise InvalidExecutionPlan("execution deadline must be finite")
        if (
            not isfinite(self.attempt_timeout_seconds)
            or self.attempt_timeout_seconds <= 0
        ):
            raise InvalidExecutionPlan("attempt timeout must be finite and positive")


@dataclass(frozen=True, slots=True)
class ModelBinding:
    model_id: str
    provider_id: str

    def __post_init__(self) -> None:
        require_identifier(self.model_id, "binding model ID")
        require_identifier(self.provider_id, "binding provider ID")


@dataclass(frozen=True, slots=True)
class InferenceRequest:
    context: ExecutionContext
    prompt: str
    constraints: RoutingConstraints
    catalog: CatalogSnapshot
    token_bounds: tuple[CandidateTokenBounds, ...]
    bindings: tuple[ModelBinding, ...]
    policy: RoutingPolicy
    baseline: Baseline
    limits: ExecutionLimits

    def __post_init__(self) -> None:
        if self.baseline.task_class != self.constraints.task_class:
            raise InvalidExecutionPlan("baseline must match the routing task class")

        model_ids = {model.model_id for model in self.catalog.models}
        bound_model_ids = {binding.model_id for binding in self.bindings}
        if len(bound_model_ids) != len(self.bindings) or bound_model_ids != model_ids:
            raise InvalidExecutionPlan(
                "the catalog must have exactly one provider binding per model"
            )


@dataclass(frozen=True, slots=True)
class ProviderCall:
    context: ExecutionContext
    attempt_id: str
    binding: ModelBinding
    prompt: str
    maximum_usage: TokenUsage


@dataclass(frozen=True, slots=True)
class ProviderOutcome:
    kind: ProviderOutcomeKind
    source: UsageSource = UsageSource.UNKNOWN
    usage: TokenUsage | None = None
    output: str | None = None
    provider_fault: bool = False

    def __post_init__(self) -> None:
        if (self.source is UsageSource.UNKNOWN) != (self.usage is None):
            raise ProviderContractError("provider usage and source disagree")
        if self.kind is ProviderOutcomeKind.SUCCEEDED:
            if self.output is None or self.provider_fault:
                raise ProviderContractError("invalid successful provider outcome")
        elif self.output is not None:
            raise ProviderContractError("a failed provider outcome includes output")

        if (
            self.kind is ProviderOutcomeKind.TRANSIENT_REJECTED
            and self.usage is not None
            and (self.usage.input_tokens != 0 or self.usage.output_tokens != 0)
        ):
            raise ProviderContractError(
                "a confirmed rejection cannot report consumed tokens"
            )


@dataclass(frozen=True, slots=True)
class AttemptIntent:
    context: ExecutionContext
    attempt_id: str
    binding: ModelBinding
    candidate: RankedCandidate


@dataclass(frozen=True, slots=True)
class AttemptFinalization:
    context: ExecutionContext
    attempt: AttemptUsage
    outcome: ProviderOutcomeKind | None
    dispatched: bool


@dataclass(frozen=True, slots=True)
class InferenceResult:
    status: ExecutionStatus
    routing: RoutingResult
    attempts: tuple[AttemptUsage, ...]
    accounting: ExecutionAccounting
    output: str | None = None
    model_id: str | None = None
