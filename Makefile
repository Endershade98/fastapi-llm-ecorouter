.PHONY: install lint format format-check typecheck test test-unit test-integration test-e2e coverage quality

install:
	python -m pip install -r requirements-dev.txt
	python -m pip install -e .

lint:
	python -m ruff check .

format:
	python -m ruff format .

format-check:
	python -m ruff format --check .

typecheck:
	python -m mypy src/

test:
	python -m pytest -v

test-unit:
	python -m pytest tests/unit -v

test-integration:
	python -m pytest tests/integration -v

test-e2e:
	python -m pytest tests/e2e -v

coverage:
	python -m pytest --cov=eco_router --cov-branch --cov-report=term-missing

quality: lint format-check typecheck test
