# Backlog

Ideas outside the current milestone, one line each. Not implemented unless asked.

## Seeded from SPEC.md §14

- Inspect AI `.eval`/`.json` log adapter; deepeval, ragas, LangSmith export adapters.
- `eval-preflight explain <check>` command.
- Per-slice coverage (by metadata key).
- Emit an OpenTelemetry/Logfire attribute set with the verdict.
- Pre-commit hook and a pytest plugin (`assert_integrity(report)`).
- Upstream contributions: pydantic-evals coverage counts (#7928) and name-collision fix (#10636).

## Found during M1

- Reject or flag NaN/inf score values; today they count as covered.
- Validate that `kind` matches the value type (e.g. `assertion` with `0.7`).
- Decide whether `name-collision` (b) should tolerate evaluators that emit several named outputs from one source (pydantic-evals evaluators can return a dict) before the M2 adapter assigns ids.
- Option to show full case lists instead of truncating at five in terminal output.

## Found during M2

- **Open question (blocks scenario C):** pydantic-evals can only give case `a` one assertion and case `b` three via case-level evaluators (coverage FAIL: each covers half the case-runs) or one evaluator returning a dict of named assertions (name-collision (b) FAIL: one id, several display names). SPEC §9 C expects "nothing else fails". Decide which check bends, or restate C, before generating it.
- In-memory `EvaluationReport` path (`reported_aggregates` from `report.averages()`, `source_version`); needs pydantic-evals as an optional extra, which requires Python ≥ 3.11.
- Optional `--source-version` flag for JSON reports, which do not record the producing version.
