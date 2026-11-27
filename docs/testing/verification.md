# Verification

Run the following commands from the root after cloning the repository.

| Command | Result |
| --- | --- |
| `make install` | Create or reuse the project virtualenv, install development dependencies and run `pip check`. |
| `make test-unit` | Run the domain and application unit tests. |
| `make quality` | Run Ruff lint and formatting checks, mypy and pytest. |
| `make coverage` | Run pytest with branch coverage and report missing lines. |
| `bash scripts/verify.sh` | Print the Git revision and working tree, run quality checks and export branch coverage to `coverage.xml`. |
| `bash scripts/audit.sh > audit.txt` | Capture revision, tracked file inventory, setup files and local tool availability for review. |
| `docker compose -f docker/compose.yaml run --build --rm quality` | Run quality checks in a Linux Python 3.12 container. |

Select the interpreter used to create a new default environment with
`make install PYTHON_BOOTSTRAP=python3.12`. For an existing virtualenv at a
different location, supply its executable as `PYTHON=/path/to/venv/bin/python`
to the Make commands.

Review audit output before sharing it. The report includes the contents of the
listed setup files and README.

## PostgreSQL integration

The ledger integration tests create a temporary schema, apply the Alembic
migration and exercise the adapter against PostgreSQL. Use the dedicated
Compose test database with its local test credentials.

```sh
docker compose -p ecorouter -f docker/compose.yaml up -d --wait postgres
docker compose -p ecorouter -f docker/compose.yaml run --build --rm \
  -e ECOROUTER_TEST_DATABASE_URL=postgresql://ecorouter:ecorouter-test@postgres/ecorouter \
  quality make test-integration
docker compose -p ecorouter -f docker/compose.yaml --profile integration down
```

For an existing development database, set `ECOROUTER_DATABASE_URL` and run
`.venv/bin/alembic upgrade head` from the repository root. The application
obtains a bounded async connection pool through `postgres_pool`. Usage
summaries group attempts by tenant, mode and the UTC time of intent creation.
The ledger emits OpenTelemetry spans when the host configures an SDK and
exporter.
