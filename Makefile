PYTHON_BOOTSTRAP ?= python3
PYTHON ?= .venv/bin/python

.PHONY: check-venv

.PHONY: install lint format format-check typecheck test test-unit test-integration test-e2e coverage quality

install:
ifeq ($(origin PYTHON),file)
	@test -x "$(PYTHON)" || "$(PYTHON_BOOTSTRAP)" -m venv .venv
endif
	@$(MAKE) check-venv
	"$(PYTHON)" -m pip install -r requirements-dev.txt
	"$(PYTHON)" -m pip install -e .
	"$(PYTHON)" -m pip check

check-venv:
	@test -x "$(PYTHON)" || { echo 'Interprete assente. Esegui make install.' >&2; exit 1; }
	@"$(PYTHON)" -c 'import sys; sys.exit("Serve un virtualenv") if sys.prefix == sys.base_prefix else print(sys.executable)'

lint: check-venv
	"$(PYTHON)" -m ruff check .

format: check-venv
	"$(PYTHON)" -m ruff format .

format-check: check-venv
	"$(PYTHON)" -m ruff format --check .

typecheck: check-venv
	"$(PYTHON)" -m mypy src/

test: check-venv
	"$(PYTHON)" -m pytest -v

test-unit: check-venv
	"$(PYTHON)" -m pytest tests/unit -v

test-integration: check-venv
	"$(PYTHON)" -m pytest tests/integration -v

test-e2e: check-venv
	"$(PYTHON)" -m pytest tests/e2e -v

coverage: check-venv
	"$(PYTHON)" -m pytest --cov=eco_router --cov-branch --cov-report=term-missing

quality: lint format-check typecheck test
