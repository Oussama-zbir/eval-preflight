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

# Milestone 1 fixtures are hand-written generic files; generated pydantic-evals
# fixtures (scripts/make_fixtures.py) arrive in Milestone 2.
fixtures:
	@echo "No generated fixtures yet (Milestone 2)."
