.PHONY: check lint format typecheck test fixtures promptfoo-fixtures dogfood research

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

# Runs the real promptfoo (pinned in the script) through npx; needs Node.js.
promptfoo-fixtures:
	uv run --no-project scripts/make_promptfoo_fixtures.py

# Runs two public pydantic-evals examples (versions pinned in the script); downloads the
# pydantic-ai-examples wheel from PyPI and checks its sha256.
dogfood:
	uv run --no-project scripts/make_dogfood_reports.py

# Probes eval frameworks for docs/research-notes.md (versions pinned in each script); the
# promptfoo probe needs Node.js.
research:
	uv run --no-project scripts/research/inspect_ai_probe.py
	uv run --no-project scripts/research/promptfoo_probe.py
