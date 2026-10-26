.PHONY: check lint format typecheck test fixtures

check: lint typecheck test

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

test:
	uv run pytest --cov --cov-report=term-missing

# Runs the real pydantic-evals (pinned in the script) in an isolated uv environment.
fixtures:
	uv run --no-project scripts/make_fixtures.py
