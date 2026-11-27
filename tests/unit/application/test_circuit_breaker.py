import pytest

from eco_router.application.circuit_breaker import CircuitBreaker, CircuitState


@pytest.mark.parametrize("threshold", [0, -1, True])
def test_failure_threshold_must_be_a_positive_integer(threshold: int) -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=threshold)


@pytest.mark.parametrize("cooldown", [0.0, -1.0, float("nan"), float("inf")])
def test_cooldown_must_be_finite_and_positive(cooldown: float) -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(cooldown_seconds=cooldown)


def test_success_resets_consecutive_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=10)

    for now, fault in ((0.0, True), (1.0, False), (2.0, True)):
        permit = breaker.acquire("primary", now)
        assert permit is not None
        breaker.finish(permit, now, provider_fault=fault)

    assert breaker.state("primary", 2.0) is CircuitState.CLOSED

    permit = breaker.acquire("primary", 3.0)
    assert permit is not None
    breaker.finish(permit, 3.0, provider_fault=True)

    assert breaker.state("primary", 3.0) is CircuitState.OPEN
    assert breaker.state("secondary", 3.0) is CircuitState.CLOSED


def test_half_open_allows_one_probe_and_failed_probe_reopens_circuit() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=10)
    initial = breaker.acquire("primary", 0.0)
    assert initial is not None
    breaker.finish(initial, 0.0, provider_fault=True)

    assert breaker.acquire("primary", 9.999) is None
    assert breaker.state("primary", 10.0) is CircuitState.HALF_OPEN

    probe = breaker.acquire("primary", 10.0)
    assert probe is not None
    assert probe.probe
    assert breaker.acquire("primary", 10.0) is None

    breaker.finish(probe, 10.0, provider_fault=True)
    assert breaker.state("primary", 19.999) is CircuitState.OPEN

    next_probe = breaker.acquire("primary", 20.0)
    assert next_probe is not None
    breaker.finish(next_probe, 20.0, provider_fault=False)

    assert breaker.state("primary", 20.0) is CircuitState.CLOSED


def test_stale_completion_cannot_release_current_probe() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=10)
    stale = breaker.acquire("primary", 0.0)
    failed = breaker.acquire("primary", 0.0)
    assert stale is not None
    assert failed is not None
    breaker.finish(failed, 0.0, provider_fault=True)

    probe = breaker.acquire("primary", 10.0)
    assert probe is not None
    assert not breaker.is_current(stale)

    breaker.finish(stale, 10.0, provider_fault=False)

    assert breaker.state("primary", 10.0) is CircuitState.HALF_OPEN
    assert breaker.acquire("primary", 10.0) is None

    breaker.finish(probe, 10.0, provider_fault=None)
    assert breaker.acquire("primary", 10.0) is not None
