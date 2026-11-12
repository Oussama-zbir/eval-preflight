# Research notes: how eval frameworks report incomplete scoring

SPEC.md §2 lists nine frameworks that an exploratory scan in October 2026 looked at. That scan is
not evidence. This file records, one framework at a time, what a specific version actually does,
with the run or source that shows it. A framework is listed as verified only when its row links to
a reproducible run (a pinned script and its committed output) or to a pinned source line.

Nothing here claims a framework is wrong. Several of the behaviours below are documented choices;
the question is only what a CI gate sees when scoring is incomplete.

## The questions

Each framework is checked against the same scenarios, chosen to match eval-preflight's checks:

1. **Evaluator raises** on 3 of 4 cases. Does the run fail, and does the CLI exit non-zero?
2. **Evaluator raises, errors tolerated** (if the framework has such a setting). What is the
   headline number, and does the output record how many cases it came from?
3. **Evaluator returns no value** on 3 of 4 cases without raising. Same question.
4. **Two evaluators with the same name.** Are their results kept apart on every case?

## Status

| Framework | Version | Status | Evidence |
|---|---|---|---|
| pydantic-evals | 2.61.0, 2.66.0 | Verified | [pydantic-evals](#pydantic-evals) |
| promptfoo | 0.125.1 | Verified | [promptfoo](#promptfoo) |
| Inspect AI | 0.3.289 | Verified | [Inspect AI](#inspect-ai) |
| Logfire | | Not yet verified | |
| deepeval | | Not yet verified | |
| ragas | | Not yet verified | |
| Braintrust | | Not yet verified | |
| LangSmith | | Not yet verified | |
| Phoenix | | Not yet verified | |

Adjacent tools named in SPEC §2 (`evaltrust`, `limen-eval`, `Threadborne/eval-integrity`,
`elanthus/preflight-eval-results`) are not yet checked either.

## pydantic-evals

Versions: 2.61.0 (fixtures, [`scripts/make_fixtures.py`](../scripts/make_fixtures.py)) and
2.66.0 (the `upstream` CI job regenerates the fixtures byte-identically; dogfood reports,
[`scripts/make_dogfood_reports.py`](../scripts/make_dogfood_reports.py)). pydantic-evals is a
library; there is no CLI, so the gate is whatever the user asserts on the report.

1. **Evaluator raises.** The run completes; the failure is recorded per case as an evaluator
   failure. The judge's average is computed from the cases where it produced a value, so a judge
   that scored 1 of 4 cases reports the same `Averages` row as one that scored all 4
   ([pydantic/pydantic-ai#7928](https://github.com/pydantic/pydantic-ai/issues/7928)).
   Fixture: [`partial_coverage.json`](../tests/fixtures/pydantic_evals/partial_coverage.json).
2. Not applicable: evaluator errors never fail the run.
3. **No value.** An evaluator that returns `{}` produces no result on that case and is absent from
   the report, as is an evaluator attached to only some cases. The report does not record which
   evaluators a case had, so the two cannot be told apart from the file
   ([dogfood.md, finding 2](dogfood.md)).
4. **Same name.** Duplicates get `_2`, `_3` suffixes per case, counting only evaluators that
   succeeded on that case, so a value can be filed under another evaluator's name
   ([pydantic/pydantic-ai#10636](https://github.com/pydantic/pydantic-ai/issues/10636)).
   Fixture: [`name_shift.json`](../tests/fixtures/pydantic_evals/name_shift.json).

Also verified: with `repeat`, the single-run average and `averages()` use different estimators
(pooled vs mean of per-case means). Fixture:
[`repeat_divergence.json`](../tests/fixtures/pydantic_evals/repeat_divergence.json).

## promptfoo

Version 0.125.1. Every scenario runs `promptfoo eval` with deterministic local providers (no API
key): [`scripts/research/promptfoo_probe.py`](../scripts/research/promptfoo_probe.py)
(`make research`). Output, including exit codes and each row's assertions read back from the
export: [`research/promptfoo-0.125.1.json`](research/promptfoo-0.125.1.json). Two runs write
byte-identical output. The adapter fixtures come from a separate script
([`make_promptfoo_fixtures.py`](../scripts/make_promptfoo_fixtures.py)); export format details are
in [input-format.md](input-format.md#promptfoo-export-json).

| Scenario (c2-c4 of 4 cases) | Env | Exit | successes / failures / errors | Assertion recorded as |
|---|---|---|---|---|
| `llm-rubric` judge returns an error | | 100 | 1 / 3 / 0 | `pass: false, score: 0, graderError: true` |
| Same | `PROMPTFOO_PASS_RATE_THRESHOLD=25` | 0 | 1 / 3 / 0 | same |
| Task under test raises | | 100 | 1 / 0 / 3 | none (`failureReason` 2) |
| Same | `PROMPTFOO_PASS_RATE_THRESHOLD=25` | 0 | 1 / 0 / 3 | none |
| `javascript` assertion throws | | 100 | 1 / 3 / 0 | `pass: false, score: 0`, no flag |
| `javascript` assertion returns `undefined` | | 100 | 1 / 3 / 0 | `pass: false, score: 0`, no flag |
| Two assertions with `metric: judge` (0.25 and 1) | | 0 | 4 / 0 / 0 | row `namedScores.judge` 0.625 |

The exit code comes from the pass rate, `successes / (successes + failures + errors)`: below
`PROMPTFOO_PASS_RATE_THRESHOLD` (default 100) the CLI exits `PROMPTFOO_FAILED_TEST_EXIT_CODE`
(default 100), otherwise 0
([`src/node/doEval.ts` L1036-L1037, L1271-L1286](https://github.com/promptfoo/promptfoo/blob/0.125.1/src/node/doEval.ts#L1271-L1286)).

1. **Evaluator fails.** With the default threshold any failure exits 100, so a broken judge does
   fail CI, but as a quality failure: promptfoo's stats count it under `failures`, not `errors`.
   A broken `javascript` assertion is worse for a reader of the export: it is a plain
   `pass: false, score: 0` whose reason starts `Custom function threw error:`, with no
   `graderError` flag, so eval-preflight's adapter also reads it as a FAIL measurement.
2. **Errors tolerated.** With `PROMPTFOO_PASS_RATE_THRESHOLD=25`, both 3-of-4 failure modes exit 0.
   Task errors are in the denominator, so a run where the task raised on 3 of 4 cases has a 25%
   pass rate and passes the gate. The export still records `errors: 3`.
3. **No value.** A `javascript` assertion cannot return no value: `undefined` is turned into the
   thrown error `Custom function must return a boolean, a finite number, or a GradingResult
   object`, and recorded like scenario 1 (a failure, no flag).
4. **Same name.** Assertions sharing a `metric` are merged, not renamed: the row's
   `namedScores.judge` is their mean (0.625), and the prompt-level `metrics.namedScores.judge` is
   5, the sum over cases of both assertions' scores (4 × (0.25 + 1)). Per-assertion scores survive
   only in `gradingResult.componentResults`.

Not yet verified: `--repeat`, and exports with several prompts or providers.

## Inspect AI

Version 0.3.289. Every scenario runs through the CLI with `mockllm/model` (no API key) and
deterministic scorers: [`scripts/research/inspect_ai_probe.py`](../scripts/research/inspect_ai_probe.py)
(`make research`). Output, including exit codes and the per-sample scores read back from each
log: [`research/inspect-ai-0.3.289.json`](research/inspect-ai-0.3.289.json). Two runs write
byte-identical output.

| Scenario | Command | Exit | Log `status` | `mean` | Samples recorded |
|---|---|---|---|---|---|
| Scorer raises on c2-c4 | `inspect eval` | 0 | `error` | none | |
| Same | `inspect eval-set --retry-attempts 0` | 1 | `error` | none | |
| Same | `inspect eval --no-fail-on-error` | 0 | `success` | 1.0 | total 4, completed 1, scored 1 |
| Same | `inspect eval --fail-on-error 0.8` | 0 | `success` | 1.0 | total 4, completed 1, scored 1 |
| Scorer returns `None` on c2-c4 | `inspect eval` | 0 | `success` | 1.0 | total 4, completed 4, scored 1, unscored 0 |
| Scorer returns NaN on c2-c4 | `inspect eval` | 0 | `success` | 1.0 | total 4, completed 4, scored 1, unscored 3 |
| `judge("strict")`, `judge("lenient")` | `inspect eval` | 0 | `success` | 0.0, 1.0 | `judge` 1, `judge1` 4 |

1. **Scorer raises.** By default one sample error fails the eval: the log status is `error` and
   there are no results. But `inspect eval` exits 0 regardless; the command discards the result of
   `eval_exec`
   ([`_cli/eval.py` L1274](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0.3.289/src/inspect_ai/_cli/eval.py#L1274)).
   `inspect eval-set` exits 1 when any eval is incomplete
   ([L1720](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0.3.289/src/inspect_ai/_cli/eval.py#L1720)).
   A CI step that runs `inspect eval` must read the log status; the exit code does not carry it.
2. **Errors tolerated.** With `--no-fail-on-error`, or a `--fail-on-error` threshold that 3 of 4
   errors does not exceed, the eval succeeds and the mean is 1.0 from one sample. The log does
   record it: `completed_samples` 1 of `total_samples` 4. A gate on the metric alone passes.
3. **No value.** A scorer may return `None` (`Scorer.__call__` is typed `Score | None`). The
   sample then has no score; the scorer's `scored_samples` is 1, but `unscored_samples` is 0, and
   `completed_samples` is 4. `unscored_samples` counts only NaN values
   ([`_eval/task/results.py` L406-L415](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0.3.289/src/inspect_ai/_eval/task/results.py#L406-L415)),
   and a NaN-returning scorer is reported correctly as 1 scored, 3 unscored. With `None`, the gap
   is visible only as `scored_samples` < `total_samples`.
4. **Same name.** The second scorer is renamed `judge1` once, for the whole run; on every sample its
   value stays under `judge1`. The per-case name shift of pydantic-evals #10636 does not happen.

What a gate on Inspect logs needs, from the above: the log status, and per scorer
`scored_samples` against `total_samples`. eval-preflight does not read Inspect logs yet (an
adapter is in [BACKLOG.md](../BACKLOG.md)).
