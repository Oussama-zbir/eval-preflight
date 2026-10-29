# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- Python floor raised to 3.11; CI runs 3.11, 3.12 and 3.13.
- pydantic-evals evaluator ids use the approved `Name(key=repr(value), ...)` form with sorted keys
  (was JSON-encoded). pydantic-evals' compact one-element arguments carry no field name, so they
  render positionally: `Judge('strict')`.

### Added
- In-memory pydantic-evals path: `check_pydantic_evals(report)` and `from_pydantic_evals(report)`,
  behind the optional extra `eval-preflight[pydantic-evals]`. Adds `reported_aggregates` from
  `report.averages()` and `source_version`; the JSON path still works without the extra.
- Multi-output pydantic-evals evaluators: each named output gets its own id,
  `Name(...)[output]`.
- Golden scenario C (repeat divergence), generated from pydantic-evals 2.61.0.
- Check 6, `constant-output`: WARN when a score or label evaluator returns one value on every
  case-run where it produced one, over at least `--min-cases-for-constant` (5) case-runs.
  Assertions are exempt.
- Non-finite values (NaN, ±inf) no longer count as coverage: `evaluator-coverage` adds a FAIL
  "non-finite value" finding, and `aggregation-consistency` excludes them from both estimators.
- Check 5, `aggregation-consistency`: compares the pooled mean with the mean of per-case means
  per evaluator and for all assertions, and verifies that each reported aggregate is reproducible
  from the raw results (stating which estimator and from how many cases). New flags
  `--aggregation-tolerance` and `--strict-aggregation`.
- pydantic-evals adapter for JSON reports (`--format pydantic-evals`, auto-detected). Evaluator
  identity comes from each result's `source`, never from the display key; results without a
  source are rejected as unverifiable.
- `scripts/make_fixtures.py` (`make fixtures`): generates the golden fixtures for scenarios A, B
  and D by running pydantic-evals 2.61.0; the golden tests run on both the generic and the
  generated fixtures.

## [0.0.1] — not published

### Added
- Canonical data model (`EvalRun`, `CaseResult`, `Measurement`, `EvaluatorRef`); duplicate
  case-runs are rejected.
- Generic input adapter (JSON document or JSONL) with format auto-detection.
- Checks: `task-failures`, `evaluator-coverage`, `evaluator-errors`, `name-collision`.
- `eval-preflight check` CLI with `--format`, the three rate thresholds, `--warnings-as-errors`
  and `--quiet`; exit codes 0 (PASS/WARN), 1 (FAIL), 2 (usage error).
- Python API: `load`, `check`, `CheckResult.verdict`, `.findings`, `.raise_if_failed()`.
- Hand-written generic fixtures for golden scenarios A, B and D.
