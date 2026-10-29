# Backlog

Ideas outside the current milestone, one line each. Not implemented unless asked.

## Seeded from SPEC.md §14

- Inspect AI `.eval`/`.json` log adapter; deepeval, ragas, LangSmith export adapters.
- `eval-preflight explain <check>` command.
- Per-slice coverage (by metadata key).
- Emit an OpenTelemetry/Logfire attribute set with the verdict.
- Pre-commit hook and a pytest plugin (`assert_integrity(report)`).
- Upstream contributions: pydantic-evals coverage counts (#7928) and name-collision fix (#10636).

## Open

- Validate that `kind` matches the value type (e.g. `assertion` with `0.7`).
- Option to show full case lists instead of truncating at five in terminal output.
- Optional `--source-version` flag for JSON reports, which do not record the producing version.

## Resolved (SPEC.md §15, 2026-10-29)

- NaN/inf values: promoted into M2 as a FAIL "non-finite value" finding in evaluator-coverage, excluded from aggregation.
- Multi-output evaluators: each named output gets its own id `f"{source_id}[{key}]"`, so name-collision (b) does not fire.
- Scenario C: restated; coverage FAIL per output id is the expected finding, name-collision must not fire.
- In-memory `EvaluationReport` path: part of M2, behind the optional `pydantic-evals` extra; Python floor raised to 3.11.
- A reported aggregate with no numeric values under its name is WARN ("cannot be checked"), confirmed.
- Evaluator id format: `Name(key=repr(value), ...)` with sorted keys; positional rendering when pydantic-evals drops the field name.
