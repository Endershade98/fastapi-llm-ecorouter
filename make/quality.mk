.PHONY: lint format format-check typecheck test test-unit test-integration test-e2e coverage quality

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
	"$(PYTHON)" -m pytest --cov=eco_router --cov-branch --cov-report=term-missing $(COVERAGE_REPORT)

quality: lint format-check typecheck test
