# A judge scored 1 case in 4: what nine eval frameworks report

eval-preflight started from three behaviours in pydantic-evals. Before treating them as a general
problem, the same four scenarios were run against nine eval frameworks, one pinned version each,
with deterministic evaluators and no API keys. This page summarises what was found. Every row
links to the full entry in [research-notes.md](research-notes.md), which cites the probe script,
its committed output (two runs, byte-identical) and the source lines behind each claim.

Nothing here says a framework is broken. Most of these behaviours are documented choices, and
several frameworks record enough to reconstruct the truth. The question is narrower: **when
scoring is incomplete, what does a CI gate on the headline number see?**

## Three findings in pydantic-evals

All three come from reports written by running pydantic-evals 2.61.0
([`scripts/make_fixtures.py`](../scripts/make_fixtures.py)); CI regenerates them byte-identically
with the newest 2.x.

**1. A judge that scored 1 case of 4 reports the same average as one that scored all 4.**
`FlakyScore` returns 1.0 on `c1` and raises on `c2`-`c4`. `report.averages()` gives
`FlakyScore: 1.0`; the failures are recorded per case, but the average carries no count
([pydantic/pydantic-ai#7928](https://github.com/pydantic/pydantic-ai/issues/7928)). Fixture:
[`partial_coverage.json`](../tests/fixtures/pydantic_evals/partial_coverage.json).

```console
FAIL  evaluator-coverage      FlakyScore() scored 1/4 case-runs (25%)
FAIL  evaluator-errors        FlakyScore() errored on 3/4: RuntimeError: judge quota exhausted
```

**2. A score can be filed under another evaluator's name.** Two evaluators with the same default
name get `_2`, `_3` suffixes per case, counting only those that succeeded on that case. When the
strict `Judge` raises, the lenient one's 1.0 is stored as `Judge`, and the `Judge` average mixes two
rubrics ([pydantic/pydantic-ai#10636](https://github.com/pydantic/pydantic-ai/issues/10636)).
Fixture: [`name_shift.json`](../tests/fixtures/pydantic_evals/name_shift.json); the full output is
in the [README](../README.md#the-problem-in-ten-seconds).

**3. The assertion pass rate changes estimator with `repeat`.** For a single run, `averages()`
pools every assertion (passing / total). With `repeat` > 1 it averages the per-case summaries
instead (`pydantic_evals/reporting/__init__.py` in the 2.61.0 wheel: L399-L411, pooling at
L258-L262, mean of means at L313-L316). Case `a` passes 1 assertion and case `b` fails 3, with no
errors and a deterministic task; with `repeat=2`, `averages()` reports 0.5, the pooled rate is 0.25.
Fixture: [`repeat_divergence.json`](../tests/fixtures/pydantic_evals/repeat_divergence.json).

```console
WARN  aggregation-consistency all assertions: pooled mean 0.25 vs mean of per-case means 0.5
```

With the in-memory path (`check_pydantic_evals(report)`), eval-preflight also states which estimator
the framework used and from how many cases: `reported "FlakyScore" = 1 reproduced from 1 of 4
cases` ([`tests/test_golden.py`](../tests/test_golden.py)).

## The same scenarios in nine frameworks

Four cases. Scenarios: an evaluator **raises** on 3 of 4 cases; it **returns no value** on 3 of 4
without raising; two evaluators share **one name** (strict scores 0.0, lenient 1.0).

| Framework | Evaluator raises: default gate | Headline from 1 of 4 scored | Count next to it | No value, no raise | Same name |
|---|---|---|---|---|---|
| [pydantic-evals](research-notes.md#pydantic-evals) 2.61.0 | library, run completes | 1.0 | no (per-case failures only) | absent; indistinguishable from "not attached" | per-case suffix shift; averages mix rubrics |
| [promptfoo](research-notes.md#promptfoo) 0.125.1 | exit 100, counted as `failures` | n/a: pass rate 25% | `graderError` per assertion; `errors` counts task errors only | `javascript` returning `undefined` becomes an unflagged failure | merged: row mean 0.625 |
| [Inspect AI](research-notes.md#inspect-ai) 0.3.289 | log status `error`, `inspect eval` exits 0 | 1.0 with `--no-fail-on-error` | yes, `completed_samples` 1 of 4 | `None`: `unscored_samples` 0, only `scored_samples` 1 shows it | kept apart (`judge`, `judge1`) |
| [deepeval](research-notes.md#deepeval) 4.3.4 | exit 1; saved run says 4 passed | n/a: per-case pass/fail | `metricsScores.errors` 3 | silent pass, exit 0 | kept by position; summary merged |
| [ragas](research-notes.md#ragas) 0.4.4 | returns normally, NaN | 1.0 | no | NaN: same, unlogged; `None`: `evaluate()` raises, all scores lost | overwritten: strict 0.0 lost |
| [Braintrust](research-notes.md#braintrust) 0.51.0 | exit 0 (only task errors fail) | 1.0 | no (`scorer_errors` per case) | `null`, silent | overwritten: strict 0.0 lost |
| [LangSmith](research-notes.md#langsmith) 0.14.9 | returns normally; no fail option | 1.0 (`to_pandas()`) | no; `extra.error` dropped by `to_pandas()` | `score: None` silent | `to_pandas()` keeps the last |
| [Phoenix](research-notes.md#phoenix) 22.0.0 | returns normally; no fail option | 1.0 (server mean) | yes, `scoreCount` 1, `errorCount` 3 | `{"score": None}` silent, `scoreCount` shows it | earlier evaluator never runs |
| [Logfire](research-notes.md#logfire) 6.0.0 + pydantic-evals 2.71.0 | spans exported, status UNSET | 1.0 (experiment span) | no; errors only on child spans | same attributes as a raise | suffix shift survives export |

Versions and modes are those in the research notes: local or offline modes throughout, so where a
hosted server computes its own summary (Braintrust, LangSmith with uploads) that summary was not
probed. Phoenix's row is the experiments API; its `evaluate_dataframe` stops at the first failing
row by default and marks the rest `DID NOT RUN`.

## The pattern

**The headline is a mean over the values that exist.** In seven of nine, a judge that scored 1 case
of 4 reports 1.0, the number a perfect judge on all 4 would get. Only promptfoo (failures count as
0) and deepeval (per-case pass/fail) do not compute it that way. Of the seven, two put the count
beside the number: Phoenix (`scoreCount`, `errorCount`) and Inspect AI (`completed_samples`). The
other five require the reader to rebuild it from per-case data.

**Evaluator errors rarely fail the run.** promptfoo and deepeval exit non-zero by default. Inspect
AI marks the log as failed but `inspect eval` still exits 0 (`inspect eval-set` exits 1). The
others complete normally; pydantic-evals, LangSmith and Phoenix experiments have no setting that
makes an evaluator error fail the run.

**"No value" is quieter than an error.** Where a framework accepts an empty result (`None`, `{}`,
NaN or `score: None`, depending on the framework), it is recorded without an error everywhere except
deepeval, which counts it in `metricsScores.errors` and still passes the test case.

**Same-name evaluators are rarely kept apart.** Only Inspect AI renames the second one consistently
for the whole run. The others merge, overwrite, run only one, or (pydantic-evals) shift names case
by case. In ragas, Braintrust and Phoenix the saved results cannot show the problem afterwards;
it has to be checked before the run, from the evaluator list.

## What a gate needs

From all nine entries, the same four things: per evaluator, the number of cases with a finite value
against the number of cases that ran; evaluator errors and task errors counted apart from real
zeros; evaluator identity that does not depend on the display name; and the estimator behind each
reported aggregate. Those are eval-preflight's `evaluator-coverage`, `evaluator-errors` /
`task-failures`, `name-collision` and `aggregation-consistency` checks
([checks.md](checks.md)).

eval-preflight reads pydantic-evals and promptfoo results directly, and any framework through the
[generic format](input-format.md). Adapters for Inspect AI, deepeval, ragas and LangSmith are on the
[backlog](../BACKLOG.md), not built.

## Limits of this comparison

- One version per framework, probed in November 2026. Behaviour may change in later releases; each
  probe is rerun by `make research`.
- Deterministic evaluators stand in for LLM judges. The failure modes are about bookkeeping, not
  model output, so this does not change what is recorded, but no real judge was called.
- Hosted UIs and server-side summaries were not probed, except Phoenix's server, run locally.
- [dogfood.md](dogfood.md) records where eval-preflight itself gets it wrong on public examples,
  including six false-positive coverage failures on evaluators that are partial by design.
