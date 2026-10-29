# eval-preflight

A pre-flight check for eval results. It catches partial runs, failed judges, mislabelled scores and
inconsistent aggregation, so the number you gate on is the number your eval actually produced.

**Status: alpha (0.0.3).** Not yet on PyPI; the first PyPI release will be 0.1.0.
[SPEC.md](SPEC.md) is the contract the code is built against.

## The problem in ten seconds

An LLM judge scores 1 case out of 4 and raises on the other 3. pydantic-evals reports its average as
1.0, the same number a judge that scored all 4 cases would produce
([pydantic/pydantic-ai#7928](https://github.com/pydantic/pydantic-ai/issues/7928)). A `score >= 0.8`
gate passes on evidence that mostly does not exist.

Two evaluators share a default name and one fails on a case: the survivor's score is filed under the
failed one's name for that case
([pydantic/pydantic-ai#10636](https://github.com/pydantic/pydantic-ai/issues/10636)). The headline
`Judge` average mixes two different rubrics.

Neither run raised. Both produce a clean-looking table. eval-preflight reads the raw per-case results
and answers one question before anyone acts on the number: *can these numbers be trusted as a
description of this run?*

```console
$ eval-preflight check name_shift.json
eval-preflight  name_shift · 4 cases · pydantic-evals

PASS  task-failures           0/4
FAIL  evaluator-coverage      Judge('strict') scored 1/4 case-runs (25%)
PASS  evaluator-coverage      Judge('lenient') scored 4/4 case-runs (100%)
FAIL  evaluator-errors        Judge('strict') errored on 3/4: RuntimeError: judge quota exhausted
PASS  evaluator-errors        Judge('lenient') errored on 0/4
FAIL  name-collision          "Judge" → Judge('strict') on c1; Judge('lenient') on c2, c3, c4
FAIL  name-collision          Judge('lenient') → "Judge_2" on c1; "Judge" on c2, c3, c4
PASS  aggregation-consistency Judge('strict'): pooled = mean of per-case means = 0
PASS  aggregation-consistency Judge('lenient'): pooled = mean of per-case means = 1
PASS  constant-output         no score or label evaluator returned a single value on ≥5 case-runs

Verdict: FAIL (4 failures, 0 warnings)
```

That file is [`tests/fixtures/pydantic_evals/name_shift.json`](tests/fixtures/pydantic_evals/name_shift.json),
a report written by the real pydantic-evals 2.61.0 ([`scripts/make_fixtures.py`](scripts/make_fixtures.py)).

## Install

Python 3.11+. Runtime dependencies: pydantic and rich. No network access, no telemetry.

```console
$ pip install "eval-preflight @ git+https://github.com/Oussama-zbir/eval-preflight@v0.0.3"
```

From 0.1.0: `pip install eval-preflight`. For the in-memory pydantic-evals path add the extra:
`eval-preflight[pydantic-evals]`.

## Quickstart

### CLI

```console
$ eval-preflight check results.json                         # format auto-detected
$ eval-preflight check results.json --baseline main.json    # also compare with a baseline run
$ eval-preflight check results.json --json > preflight.json # machine-readable report
```

Exit codes: `0` PASS (or WARN), `1` FAIL (or WARN with `--warnings-as-errors`), `2` the check could not
run (unreadable file, unknown format, bad flag). Every threshold is a flag; see
`eval-preflight check --help` and [docs/ci.md](docs/ci.md#choosing-flags).

### Python

```python
from eval_preflight import check, load

result = check(load("results.json"))
result.verdict             # "PASS" | "WARN" | "FAIL"
result.raise_if_failed()   # IntegrityError listing the FAIL findings
```

For a live pydantic-evals report, without writing it to disk:

```python
from eval_preflight import check_pydantic_evals

report = dataset.evaluate_sync(task)
check_pydantic_evals(report).raise_if_failed()
```

The live report also carries the framework's own averages, so `aggregation-consistency` can check
that each reported number is reproducible from the raw results, and from how many cases.

### CI

Run the evals, then gate on the pre-flight before anything reads the score.
[`examples/github-action.yml`](examples/github-action.yml) is a complete workflow; this repository's
CI runs its pre-flight steps against a clean run (must pass) and a partial run (must fail).
Flags, baselines and the JSON schema: [docs/ci.md](docs/ci.md).

## What it checks

| Check | Fails or warns when | Default |
|---|---|---|
| `task-failures` | the task under test raised on a case-run | FAIL above 0% |
| `evaluator-coverage` | an evaluator has no value on some case-runs; any NaN/inf value | FAIL below 100%; FAIL on any non-finite value |
| `evaluator-errors` | an evaluator raised on a case-run (most common message shown) | FAIL above 0% |
| `name-collision` | one display name maps to several evaluators, or one evaluator to several names | FAIL |
| `aggregation-consistency` | pooled mean and mean of per-case means disagree; a reported aggregate matches neither | WARN (FAIL with `--strict-aggregation`); FAIL |
| `constant-output` | a score or label evaluator returned one value on every case-run where it produced one (≥ 5) | WARN |
| `baseline-comparability` | cases or evaluators differ from `--baseline`; coverage dropped; repeat counts differ | WARN; FAIL on a coverage drop |

Evaluator identity comes from the framework's evaluator spec (`Judge(rubric='strict')`), never from
the display name, because the display name is one of the things being checked. Each check, its
rationale, thresholds and example output: [docs/checks.md](docs/checks.md).

Why aggregation gets its own check: with `repeat=2`, case `a` passing 1 assertion and case `b` failing
3, the pooled assertion pass rate is 0.25 and the mean of per-case means is 0.5. pydantic-evals'
`report.averages()` reports 0.5; eval-preflight says so and names the estimator (golden scenario C,
[`tests/test_golden.py`](tests/test_golden.py)).

## Supported inputs

| Input | How | Notes |
|---|---|---|
| Generic JSON / JSONL | `--format generic` | One `CaseResult` per case-run; any framework can export it. [docs/input-format.md](docs/input-format.md) |
| pydantic-evals JSON | `--format pydantic-evals` | `TypeAdapter(EvaluationReport).dump_json(report, by_alias=True)`; pydantic-evals not required |
| pydantic-evals in memory | `check_pydantic_evals(report)` | Adds the reported averages and the pydantic-evals version |

The pydantic-evals adapter is tested against reports generated by running pydantic-evals 2.61.0, not
hand-written JSON. A result without its evaluator `source` is rejected rather than attributed by name.

## Relation to other eval tools

eval-preflight runs *before* the statistics. It says whether a run's numbers describe that run; it
does not say whether model A beats model B.

- [`evaltrust`](https://github.com/k-dickinson/evaltrust) ("an auditor for LLM evaluations") checks
  how much confidence a comparison between eval results deserves.
- [`limen-eval`](https://github.com/KurathSec/limen) measures the same-configuration noise floor from
  repeated runs: per-item flakiness and sign stability.

They are complementary: a significance test on a mean computed from a quarter of the cases is
precise about the wrong number.

## Limitations

- Two input formats: generic and pydantic-evals. promptfoo is planned; Inspect AI, deepeval, ragas
  and LangSmith are on the [backlog](BACKLOG.md).
- It checks completeness, attribution and arithmetic. It does not judge whether an evaluator or
  rubric is any good; `constant-output` is a heuristic for a stuck judge, not proof.
- Identity is only as good as the framework's evaluator spec. pydantic-evals omits the field name
  for a single positional argument, so the id renders positionally (`Judge('strict')`) and is not
  comparable with an id written by hand in the generic format.
- JSON reports from pydantic-evals do not record the producing version or the framework's averages;
  only the in-memory path can check reported aggregates.
- Alpha: the data model is stable from 0.1.0; flags and messages may still change before then.

## Development

```console
$ uv sync
$ make check      # ruff, ruff format --check, mypy --strict, pytest with coverage >= 95%
$ make fixtures   # regenerate the pydantic-evals fixtures by running the pinned library
```

Golden scenarios A–E in [SPEC.md §9](SPEC.md) are the acceptance tests; the clean run must always
pass. CI also builds the wheel, installs it in a fresh virtualenv and runs the quickstart against it
([`scripts/smoke_dist.sh`](scripts/smoke_dist.sh)).

## License

MIT
