# Using eval-preflight in CI

Run your evals, then run `eval-preflight check` on the results before anything reads the
headline number. The exit code is the gate.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Verdict PASS, or WARN without `--warnings-as-errors` |
| `1` | Verdict FAIL, or WARN with `--warnings-as-errors` |
| `2` | Usage error: unreadable or unrecognised file (results or baseline), bad flag |

A `2` means the check did not run. Treat it as a failure; do not let a missing results file
pass the gate.

## GitHub Actions

[`examples/github-action.yml`](../examples/github-action.yml) is a complete workflow. Replace the
"Run evals" step with your own. The pre-flight step writes a JSON report for the artifact, then
runs again for a readable log and to set the exit status:

```yaml
- name: Pre-flight check
  id: preflight
  run: |
    eval-preflight check "$RESULTS" --json > preflight.json || true
    eval-preflight check "$RESULTS"
```

This repository's CI runs that step against its clean-run fixture (must pass) and the
partial-coverage fixture (must fail), using `scripts/run_action_example.py`, which executes the
example's `preflight*` steps with the same bash flags GitHub uses.

eval-preflight is not on PyPI yet; the example installs a tagged release from GitHub.

## Choosing flags

The defaults are strict: any task failure, any missing or errored evaluator value, any name
collision and any non-finite value fails the run. Relax a default only for a reason you could
explain in review:

- `--max-task-failure-rate 0.02`: tolerate a known flaky upstream on a large suite.
- `--min-coverage 0.95` / `--max-evaluator-error-rate 0.05`: an LLM judge with occasional
  rate-limit errors. The coverage finding still prints `n/N`, so the gap stays visible.
- `--strict-aggregation`: fail when the pooled mean and the mean of per-case means disagree,
  for gates that compare numbers across runs with different repeat settings.
- `--warnings-as-errors`: make every WARN (constant output, aggregation divergence, baseline
  differences) block the merge.

Name collisions and non-finite values have no threshold.

## Comparing with a baseline

Store the results of the main branch (an artifact or a committed file) and pass them as
`--baseline`. The run then also fails if an evaluator's coverage dropped, and warns if cases,
evaluators or repeat counts differ. `--require-same-cases` turns case and evaluator differences
into failures, which is what a gate that compares scores between the two runs needs.

```console
$ eval-preflight check results.json --baseline main-results.json --require-same-cases
```

## JSON report

`--json` prints exactly one JSON document on stdout and nothing else (usage errors go to stderr,
with stdout empty). The exit code is the same as without `--json`. `--quiet` has no effect.

```json
{
  "verdict": "FAIL",
  "run": {
    "name": "partial_coverage",
    "source": "pydantic-evals",
    "source_version": null,
    "cases": 4,
    "case_runs": 4,
    "evaluators": ["FlakyScore()", "AlwaysScores()"],
    "baseline": null
  },
  "findings": [
    {
      "check": "evaluator-coverage",
      "severity": "FAIL",
      "message": "FlakyScore() scored 1/4 case-runs (25%)",
      "details": {"evaluator_id": "FlakyScore()", "covered": 1, "eligible": 4, "...": "..."}
    }
  ]
}
```

`run.baseline` has the same shape as `run` when `--baseline` is given. Each check's `details` are
listed in [checks.md](checks.md). The output is always valid JSON: non-finite numbers never
appear (values the checks report as non-finite are strings).

## Python

```python
from eval_preflight import check, load

result = check(load("results.json"), baseline=load("main-results.json"))
print(result.to_json())
result.raise_if_failed()   # IntegrityError listing the FAIL findings
```
