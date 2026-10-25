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
