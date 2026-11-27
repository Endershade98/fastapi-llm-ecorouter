from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class CircuitPermit:
    provider_id: str
    generation: int
    probe: bool


@dataclass(slots=True)
class _ProviderCircuit:
    failures: int = 0
    generation: int = 0
    reopen_at: float | None = None
    probe_in_flight: bool = False


class CircuitBreaker:
    """Per-provider circuit for use from a single event loop.

    Transitions are synchronous. A generation change invalidates completions
    from calls admitted before the transition.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> None:
        if (
            isinstance(failure_threshold, bool)
            or not isinstance(failure_threshold, int)
            or failure_threshold <= 0
        ):
            raise ValueError("failure threshold must be a positive integer")
        if not isfinite(cooldown_seconds) or cooldown_seconds <= 0:
            raise ValueError("cooldown must be finite and positive")

        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._providers: dict[str, _ProviderCircuit] = {}

    def state(self, provider_id: str, now: float) -> CircuitState:
        circuit = self._providers.get(provider_id)
        if circuit is None or circuit.reopen_at is None:
            return CircuitState.CLOSED
        if now < circuit.reopen_at:
            return CircuitState.OPEN
        return CircuitState.HALF_OPEN

    def acquire(self, provider_id: str, now: float) -> CircuitPermit | None:
        circuit = self._providers.setdefault(provider_id, _ProviderCircuit())
        state = self.state(provider_id, now)

        if state is CircuitState.OPEN or circuit.probe_in_flight:
            return None

        probe = state is CircuitState.HALF_OPEN
        circuit.probe_in_flight = probe
        return CircuitPermit(provider_id, circuit.generation, probe)

    def is_current(self, permit: CircuitPermit) -> bool:
        circuit = self._providers[permit.provider_id]
        return permit.generation == circuit.generation

    def finish(
        self,
        permit: CircuitPermit,
        now: float,
        *,
        provider_fault: bool | None,
    ) -> None:
        """Record a result, or release a permit with no provider result."""
        circuit = self._providers[permit.provider_id]
        if not self.is_current(permit):
            return

        if permit.probe:
            circuit.probe_in_flight = False
        if provider_fault is None:
            return

        if provider_fault:
            circuit.failures += 1
            if permit.probe or circuit.failures >= self._threshold:
                circuit.reopen_at = now + self._cooldown
                circuit.generation += 1
            return

        circuit.failures = 0
        if permit.probe:
            circuit.reopen_at = None
            circuit.generation += 1
