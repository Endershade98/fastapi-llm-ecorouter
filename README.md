# EcoRouter-LLM

EcoRouter selects an LLM for a request using eligibility, quality, cost and latency
constraints. It coordinates inference attempts within token, cost and deadline limits
and accounts for usage across retries and fallback.

The current implementation contains the domain and application layers. You can
exercise both through the test suite with scripted providers and ledgers. The
infrastructure and API directories are placeholders for the next increments.

## Run the checks

### Docker

With Docker running and Docker Compose v2 available, run from the repository root:

```sh
docker compose -f docker/compose.yaml run --build --rm quality
```

This builds a Linux Python 3.12 environment and runs Ruff lint and format checks,
strict mypy and pytest. The same command works on Linux, macOS and Windows hosts
configured to run Linux containers. The test suite uses no provider credentials
or database.

### Local development

With Python 3.12 or later and GNU Make installed:

```sh
make install
make quality
```

`make install` creates `.venv` when needed. The Make targets use its Python
directly, so the shell can remain unactivated.

## Explore the repository

| Path | Purpose |
| --- | --- |
| `src/eco_router/domain/` | Candidate eligibility and ranking, pricing and usage accounting |
| `src/eco_router/application/` | Async inference orchestration, resilience and provider, ledger and analytics ports |
| `tests/unit/` | Domain and application behavior checked with deterministic test doubles |
| `make/`, `scripts/`, `docker/` | Local setup, audit and container verification |

Start with the [architecture overview](docs/architecture/overview.md) and the
[verification guide](docs/testing/verification.md).
