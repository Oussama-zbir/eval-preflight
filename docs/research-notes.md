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
| deepeval | 4.3.4 | Verified | [deepeval](#deepeval) |
| ragas | 0.4.4 | Verified | [ragas](#ragas) |
| Logfire | | Not yet verified | |
| Braintrust | 0.51.0 (Python SDK) | Verified | [Braintrust](#braintrust) |
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

## deepeval

Version 4.3.4. Every scenario runs `deepeval test run` on one parametrized pytest test (`assert_test`
over 4 cases) with deterministic metrics, no API key and telemetry off:
[`scripts/research/deepeval_probe.py`](../scripts/research/deepeval_probe.py) (`make research`).
Output, including exit codes, pytest's counts and the test run deepeval saves to
`.deepeval/.latest_test_run.json`: [`research/deepeval-4.3.4.json`](research/deepeval-4.3.4.json).
Two runs write byte-identical output. Source lines below are from the `deepeval-4.3.4` wheel on
PyPI; the GitHub repository has no tag for 4.3.4 (the latest is `v4.1.8`).

| Scenario (c2-c4 of 4 cases) | Flag | Exit | pytest | Saved run: passed / failed | Saved `metricsScores` |
|---|---|---|---|---|---|
| Custom metric raises | | 1 | 1 passed, 3 failed | 4 / 0 | passes 1, fails 0, errors 3 |
| Same | `--ignore-errors` | 1 | 1 passed, 3 failed | 1 / 3 | passes 1, fails 0, errors 3 |
| Custom metric sets no score | | 0 | 4 passed | 4 / 0 | passes 1, fails 0, errors 3 |
| `ExactMatchMetric`, no `expected_output` | | 1 | 1 passed, 3 failed | 1 / 3 | passes 1, fails 0, errors 3 |
| Same | `--skip-on-missing-params` | 0 | 4 passed | 1 / 0 (c2-c4 absent) | passes 1, fails 0, errors 0 |
| Two metrics named `judge` (strict, lenient) | | 1 | 3 passed, 1 failed | 3 / 1 | one `judge` entry: passes 4, fails 1, errors 3 |

A test case starts as passed (`success=True`,
`deepeval/test_case/api.py` L58) and each metric can only turn it to failed: `success is False`
fails it, `None` leaves it as it was (`deepeval/test_run/api.py` L86-L93). Separately, the
run-level `metricsScores` counts a metric result as an error whenever its score or success is
`None` (`deepeval/test_run/test_run.py` L290-L291).

1. **Metric raises.** The exception propagates out of `assert_test`, so pytest fails those cases
   and the CLI exits 1: a CI gate on the exit code does catch it. `deepeval.evaluate()` re-raises
   too. But the saved test run says 4 passed, 0 failed: the three cases record the metric with
   score `null`, success `null` and error `null`, so the exception text is not in the file. Only
   `metricsScores` (`errors: 3`) shows anything went wrong.
2. **Errors tolerated.** `--ignore-errors` does not let the run pass. The metric's error is
   recorded and its success set to `false` (`deepeval/metrics/indicator.py` L193-L197), so the
   cases fail and the CLI still exits 1; the saved file is now correct (1 / 3, with the error
   text). A missing required field (`expected_output` for `ExactMatchMetric`) is recorded the same
   way even without the flag, because the parameter check stores the error on the metric before
   raising (`deepeval/metrics/utils/test_case.py` L224-L226). The tolerant setting is `--skip-on-missing-params`, and it only covers
   missing fields: the metric is marked skipped and not recorded
   (`indicator.py` L165-L167), so c2-c4 pass pytest and are absent from the saved run. The CLI
   exits 0, the saved run reports 1 passed and 0 errors, and nothing in it says that 4 cases ran.
3. **No value.** A custom metric whose `measure` returns without setting `score` or `success` is
   a silent pass: the CLI exits 0, pytest reports 4 passed and the saved run 4 passed. The gap is
   visible only as `errors: 3` in `metricsScores`.
4. **Same name.** Both results are kept on every case, in the order the metrics were passed, but
   under the same `name`, so a reader of the file can tell them apart only by position. The
   run-level `metricsScores` merges them into one `judge` entry: `scores` `[0.0, 1.0, 1.0, 1.0,
   1.0]` holds the strict metric's one score and the lenient metric's four, and its `errors: 3` are
   the strict metric's three unscored cases.

What a gate on deepeval needs, from the above: per metric, the number of scored results against
the number of test cases that ran, taken from pytest's count rather than the saved run, which
omits skipped cases. eval-preflight does not read deepeval test runs yet (an
adapter is in [BACKLOG.md](../BACKLOG.md)).

## ragas

Version 0.4.4. ragas is a library with two ways to score a dataset, and both are probed with
deterministic metrics, no LLM, no API key and analytics off:
[`scripts/research/ragas_probe.py`](../scripts/research/ragas_probe.py) (`make research`). Output,
including `repr(result)`, per-row scores and the CSV each experiment saves:
[`research/ragas-0.4.4.json`](research/ragas-0.4.4.json). Two runs write byte-identical output.
The cited files are identical in the `ragas-0.4.4` wheel and the `v0.4.4` tag on GitHub.

`evaluate()` (deprecated in 0.4, still documented), one custom `SingleTurnMetric` named `judge`:

| Scenario (c2-c4 of 4 cases) | Setting | Raises | `repr(result)` | Per-row `judge` | Errors logged |
|---|---|---|---|---|---|
| Metric raises | default | no | `{'judge': 1.0000}` | 1.0, NaN, NaN, NaN | 3 |
| Same | `raise_exceptions=True` | `RuntimeError` | | | 0 |
| Metric returns NaN | default | no | `{'judge': 1.0000}` | 1.0, NaN, NaN, NaN | 0 |
| Metric returns `None` | default | `TypeError` (from `np.isnan`) | | | 0 |
| Two metrics named `judge` (strict 0.0, lenient 1.0) | default | no | `{'judge': 1.0000}` | 1.0 × 4 | 0 |

`@experiment` over a local CSV dataset, a `@numeric_metric` named `judge`:

| Scenario (c2-c4 of 4 rows) | Raises | Saved rows | `judge` in saved CSV | pandas `mean()` | Warnings printed |
|---|---|---|---|---|---|
| Metric raises | no | 4 | empty on c2-c4, error text in `reason` | 1.0 (count 1) | 0 |
| Metric returns `None` | no | 4 | empty on c2-c4, validation text in `reason` | 1.0 (count 1) | 0 |
| Experiment function raises | no | 1 | c2-c4 absent | 1.0 (count 1) | 3 |
| Experiment function returns `None` | no | 1 | c2-c4 absent | 1.0 (count 1) | 0 |

1. **Metric raises.** By default `evaluate()` does not raise: the executor logs `Exception raised
   in Job[n]` and returns NaN for that job
   ([`executor.py` L68-L84](https://github.com/vibrantlabsai/ragas/blob/v0.4.4/src/ragas/executor.py#L68-L84)). The headline is the NaN-skipping mean
   ([`utils.py` L46-L55](https://github.com/vibrantlabsai/ragas/blob/v0.4.4/src/ragas/utils.py#L46-L55), used by
   [`dataset_schema.py` L443-L446](https://github.com/vibrantlabsai/ragas/blob/v0.4.4/src/ragas/dataset_schema.py#L443-L446)), so `{'judge': 1.0000}` from 1
   of 4 rows looks exactly like a full run. `raise_exceptions=True` makes the whole call raise and
   returns nothing. In `@experiment`, a `@numeric_metric` never raises: errors become
   `value=None` with the message in `reason`
   ([`metrics/decorator.py` L301-L304](https://github.com/vibrantlabsai/ragas/blob/v0.4.4/src/ragas/metrics/decorator.py#L301-L304)); the saved CSV keeps
   the row with an empty `judge`, and a pandas mean over the column is 1.0 from one value.
2. **Errors tolerated.** That is the default in both APIs. Neither has an error threshold:
   `evaluate()` either tolerates every error or raises on the first. A failure of the experiment function itself is printed as a warning and
   the row is dropped from the saved results
   ([`experiment.py` L180-L189](https://github.com/vibrantlabsai/ragas/blob/v0.4.4/src/ragas/experiment.py#L180-L189)), so the CSV has 1 row for a 4-row
   dataset and nothing in it records that 3 rows failed.
3. **No value.** In `evaluate()`, a metric returning NaN is indistinguishable from one that raised,
   except that nothing is logged. A metric returning `None` crashes result construction
   (`np.isnan` on an object array), so the scores of every case are lost. In `@experiment`, a
   `None` from the metric is recorded like an error (empty value, reason text); a `None` from the
   experiment function silently drops the row, with no warning at all
   ([`experiment.py` L182-L184](https://github.com/vibrantlabsai/ragas/blob/v0.4.4/src/ragas/experiment.py#L182-L184)).
4. **Same name.** `evaluate()` keys each row's scores by metric name
   ([`evaluation.py` L292-L300](https://github.com/vibrantlabsai/ragas/blob/v0.4.4/src/ragas/evaluation.py#L292-L300)), so the second `judge` overwrites the
   first on every row: the strict metric's four 0.0 scores are gone and the result reports 1.0,
   with no warning. In `@experiment`, the user builds the row, so names are the user's problem.

Rows in a saved experiment are in completion order (`asyncio.as_completed`), not dataset order.
Not yet verified: the `ragas evals` CLI.

What a gate on ragas needs, from the above: per metric, the count of non-NaN values against the
dataset size (not the mean), and for `@experiment`, the saved row count against the dataset row
count. Duplicate metric names must be rejected before `evaluate()`, because its output cannot show
them. eval-preflight does not read ragas results yet.

## Braintrust

Python SDK 0.51.0. Every scenario runs one `Eval` over 4 cases with deterministic scorers, no
account and no API key, in local mode (`no_send_logs`; the CLI then skips `login`,
[`cli/eval.py` L317-L322](https://github.com/braintrustdata/braintrust-sdk-python/blob/py-sdk-v0.51.0/py/src/braintrust/cli/eval.py#L317-L322)):
[`scripts/research/braintrust_probe.py`](../scripts/research/braintrust_probe.py) (`make research`).
Each scenario is run through `braintrust eval --no-send-logs --jsonl`, for the exit code and the
summary a CI log shows, and through `Eval(..., no_send_logs=True)` in-process, for the per-case
results. Output: [`research/braintrust-0.51.0.json`](research/braintrust-0.51.0.json). Two runs
write byte-identical output. The cited files are identical in the `braintrust-0.51.0` wheel and
the `py-sdk-v0.51.0` tag of `braintrustdata/braintrust-sdk-python`.

| Scenario (c2-c4 of 4 cases) | Setting | Exit | CLI prints | `judge` per case | Exception lines |
|---|---|---|---|---|---|
| Scorer raises | default | 0 | `judge` 1.0 | 1.0, absent × 3 (`scorer_errors` in metadata) | 3 |
| Same | `default_error_score_handler` | 0 | `judge` 0.25 | 1.0, 0 × 3 | 3 |
| Scorer returns `None` | default | 0 | `judge` 1.0 | 1.0, `null` × 3 | 0 |
| Two scorers return `Score(name="judge")` (strict 0.0, lenient 1.0) | default | 0 | `judge` 1.0 | 1.0 × 4 | 0 |
| Task raises | default | 1 | 3 errors, no summary | 1.0, absent × 3 | 0 |
| Same | `default_error_score_handler` | 1 | 3 errors, no summary | 1.0, 0 × 3 | 0 |

Only a task error fails the run: the default reporter counts results whose `error` is set
([`framework.py` L677](https://github.com/braintrustdata/braintrust-sdk-python/blob/py-sdk-v0.51.0/py/src/braintrust/framework.py#L677)), and that field holds only the task's
exception. A scorer's exception is caught per scorer, written to `metadata.scorer_errors` and
printed to stderr ([`framework.py` L1932-L1941](https://github.com/braintrustdata/braintrust-sdk-python/blob/py-sdk-v0.51.0/py/src/braintrust/framework.py#L1932-L1941)). The
summary is the mean of the scores that exist, with no count beside it
([`framework.py` L2090-L2097](https://github.com/braintrustdata/braintrust-sdk-python/blob/py-sdk-v0.51.0/py/src/braintrust/framework.py#L2090-L2097)). That is how the local
summary is built; with logs sent, the summary comes from the Braintrust server, which this probe
does not run.

1. **Scorer raises.** The CLI exits 0 and prints `judge` 1.0, the same line as a run in which all
   4 cases scored 1.0. The only signs are three "Found exceptions for the following scorers" lines
   on stderr and `scorer_errors` in each case's metadata. A task that raises does fail the CLI
   (exit 1, the errors printed instead of the summary). In-process, `Eval()` returns normally in
   both cases and its summary is again `judge` 1.0 from 1 of 4.
2. **Errors tolerated.** Tolerating is the default for scorer errors. The opt-in
   `error_score_handler` (default `None`,
   [`framework.py` L446](https://github.com/braintrustdata/braintrust-sdk-python/blob/py-sdk-v0.51.0/py/src/braintrust/framework.py#L446)) goes the other way: the SDK's
   `default_error_score_handler` scores every scorer that did not run as 0
   ([`framework.py` L1556-L1563](https://github.com/braintrustdata/braintrust-sdk-python/blob/py-sdk-v0.51.0/py/src/braintrust/framework.py#L1556-L1563)), so the summary drops to
   0.25. That is the honest number for a pass rate, but a 0 written by the handler cannot be told
   apart from a real 0 in `scores`; only `scorer_errors` (scorer failed) or the task error
   records the difference.
3. **No value.** A bare `None` becomes `Score(name, score=None)`
   ([`framework.py` L1644](https://github.com/braintrustdata/braintrust-sdk-python/blob/py-sdk-v0.51.0/py/src/braintrust/framework.py#L1644)): the case records `judge: null`, nothing
   is printed, and the summary skips it. Exit 0, `judge` 1.0 from 1 of 4, with no warning.
4. **Same name.** Each case's scores are a dict keyed by score name, filled in scorer order
   ([`framework.py` L1900-L1906](https://github.com/braintrustdata/braintrust-sdk-python/blob/py-sdk-v0.51.0/py/src/braintrust/framework.py#L1900-L1906)), so the second `judge`
   overwrites the first: the strict scorer's four 0.0 scores are gone and the run reports 1.0 with
   no warning.

What a gate on Braintrust needs, from the above: per score name, the number of non-null values
against the number of cases, plus `scorer_errors` and task errors counted separately from real
zeros, and a check for duplicate score names before the run, because the results cannot show them.
eval-preflight does not read Braintrust experiments yet.
