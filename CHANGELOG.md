# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
