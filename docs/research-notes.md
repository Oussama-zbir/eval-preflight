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
| Logfire | 6.0.0 (SDK), with pydantic-evals 2.71.0 | Verified (exported spans) | [Logfire](#logfire) |
| Braintrust | 0.51.0 (Python SDK) | Verified | [Braintrust](#braintrust) |
| LangSmith | 0.14.9 (Python SDK) | Verified | [LangSmith](#langsmith) |
| Phoenix | 22.0.0 (server), client 3.7.0, evals 3.10.0 | Verified | [Phoenix](#phoenix) |

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

## LangSmith

Python SDK 0.14.9. Every scenario runs `evaluate()` over 4 in-memory examples with an exact-match
evaluator, no account, no API key and no network: `upload_results=False` (marked beta), and a client
pointed at a closed loopback port
([`scripts/research/langsmith_probe.py`](../scripts/research/langsmith_probe.py), `make research`).
Output, including each case's evaluation results, the `feedback.*` columns of `to_pandas()` and
the error lines LangSmith logged: [`research/langsmith-0.14.9.json`](research/langsmith-0.14.9.json).
Two runs write byte-identical output. 0.14.9 is pinned because it is the latest release with a
GitHub tag; the cited files are identical in the `langsmith-0.14.9` wheel and the `v0.14.9` tag,
and 0.15.0 (2026-11-17, untagged) only reformats `langsmith/evaluation/`.

`evaluate()` never raised and, with results not uploaded, prints no summary; the table's mean is
pandas' over the `feedback.judge` column of `to_pandas()`, the documented way to read local results.

| Scenario (c2-c4 of 4 cases) | Setting | `judge` results on c2-c4 | `feedback.judge` | Mean | Errors logged |
|---|---|---|---|---|---|
| Evaluator raises | | 2 per case, `score` `None`, `extra.error` | 1.0, None × 3 | 1.0 | 3 |
| Same, evaluator is a lambda | | none | 1.0, None × 3 | 1.0 | 3 |
| Evaluator returns `None` | | 2 per case, `score` `None`, `extra.error` (`ValueError`) | 1.0, None × 3 | 1.0 | 3 |
| Evaluator returns `{"key": "judge", "score": None}` | | 1 per case, `score` `None`, no error flag | 1.0, None × 3 | 1.0 | 0 |
| Two evaluators return key `judge` (strict 0.0, lenient 1.0) | | 2 per case (0.0 and 1.0) | 1.0 × 4 | 1.0 | 0 |
| Target raises | `error_handling="log"` (default) | 2 per case, `KeyError('answer')` | 1.0, None × 3 | 1.0 | 3 target, 3 evaluator |
| Same | `error_handling="ignore"` | same | same | 1.0 | same |

An evaluator's exception is caught per evaluator and logged, and an error result is added for
each of its `feedback_keys`, with `score` `None`, the exception's `repr` as `comment` and
`extra={"error": True}`
([`evaluation/_runner.py` L1744-L1781](https://github.com/langchain-ai/langsmith-sdk/blob/v0.14.9/python/langsmith/evaluation/_runner.py#L1744-L1781)).
Those keys are not taken from the evaluator's results: they are read statically from its source,
one per `return` of a literal `key`, without de-duplication, falling back to the function name,
and empty when the evaluator is not a `def` (a lambda, for example)
([`evaluation/_key_extraction.py` L111-L140](https://github.com/langchain-ai/langsmith-sdk/blob/v0.14.9/python/langsmith/evaluation/_key_extraction.py#L111-L140)).
The probe's evaluator returns `"judge"` in two places, hence two error results per failed case.
`to_pandas()` builds one column per key with a dict comprehension, so a later result with the
same key overwrites an earlier one, and an error result contributes `None`
([`evaluation/_runner.py` L2342-L2345](https://github.com/langchain-ai/langsmith-sdk/blob/v0.14.9/python/langsmith/evaluation/_runner.py#L2342-L2345)).

1. **Evaluator raises.** `evaluate()` returns normally and the column's mean is 1.0 from 1 of 4
   cases, the same as a full run. The in-memory results do mark the failure (`extra.error`, the
   exception in `comment`), but `to_pandas()` drops both and keeps only `None`. If the evaluator
   is a lambda, its key cannot be read from source, so no error result is added at all: the
   failed cases have no `judge` result, and the only trace is the logged error.
2. **Errors tolerated.** That is the only mode; `evaluate()` has no option to fail on evaluator
   errors. `error_handling` is about target errors and, locally, changes nothing: the target's
   exception is logged and the run kept either way
   ([`evaluation/_runner.py` L2051-L2073](https://github.com/langchain-ai/langsmith-sdk/blob/v0.14.9/python/langsmith/evaluation/_runner.py#L2051-L2073)); per its
   docstring, `"ignore"` keeps such runs out of the experiment on the server
   ([L194-L198](https://github.com/langchain-ai/langsmith-sdk/blob/v0.14.9/python/langsmith/evaluation/_runner.py#L194-L198)), which this probe does not run. The
   evaluators still run on the failed target's output, so whether a target error shows as an
   evaluator error, a low score or a pass depends on the evaluator; here, `outputs["answer"]`
   raised `KeyError` and the mean stayed 1.0.
3. **No value.** Returning `None` is rejected
   ([`evaluation/evaluator.py` L937-L941](https://github.com/langchain-ai/langsmith-sdk/blob/v0.14.9/python/langsmith/evaluation/evaluator.py#L937-L941)) and recorded
   like a raise. Returning a result with `score: None` is accepted silently: no error flag, no log
   line, and the mean is 1.0 from 1 of 4.
4. **Same name.** The in-memory results keep both on every case, in evaluator order, under the same
   key, so they can be told apart only by position. `to_pandas()` keeps the last: the strict
   evaluator's four 0.0 scores are gone and the column reads 1.0 on every case, with no warning.

With results uploaded, aggregates are computed by the LangSmith server, and LangSmith's pytest
integration is a separate path; neither is probed here.

What a gate on LangSmith results needs, from the above: per feedback key, the number of non-null
scores against the number of examples, read from the result objects rather than `to_pandas()`, and
a count of `extra.error` results and target errors. Lambda evaluators and duplicate keys must be
checked before the run, because the results cannot show them. eval-preflight does not read
LangSmith experiments yet (an adapter is in [BACKLOG.md](../BACKLOG.md)).

## Phoenix

Arize Phoenix has two ways to score a set of cases, and the probe runs both
([`scripts/research/phoenix_probe.py`](../scripts/research/phoenix_probe.py), `make research`):
experiments (`phoenix.client` 3.7.0, `Client().experiments.run_experiment`), where the task and
evaluators run in the client and a Phoenix server stores the results and computes the summary the
UI shows; and `phoenix.evals.evaluate_dataframe` (`arize-phoenix-evals` 3.10.0), which scores a
DataFrame locally. A `dry_run` experiment still fetches its dataset from a server, so the probe
starts a real `phoenix serve` (`arize-phoenix` 22.0.0) on loopback with a throwaway SQLite
database, `PHOENIX_ALLOW_EXTERNAL_RESOURCES=false` and telemetry off; no account and no network.
Output, with each case's evaluation runs, the server's GraphQL `annotationSummaries` and
`errorRate`, and each `evaluate_dataframe` row:
[`research/phoenix-22.0.0.json`](research/phoenix-22.0.0.json). Two runs write byte-identical
output. Every cited file is identical in the wheels and the tags `arize-phoenix-v22.0.0`,
`arize-phoenix-client-v3.7.0` and `arize-phoenix-evals-v3.10.0`.

Neither API raised in any scenario. Experiments print `Experiment completed: N task runs,
M evaluator runs, K evaluations`; the server summary is per evaluation name.

| Scenario (c2-c4 of 4 cases) | Experiment: printed summary | Server `judge`: mean, count, `scoreCount`, `errorCount` |
|---|---|---|
| Evaluator raises | 4 task runs, 1 evaluator runs, 1 evaluations | 1.0, 4, 1, 3 |
| Evaluator returns `None` | same | 1.0, 4, 1, 3 |
| Evaluator returns `{"score": None}` | 4 task runs, 1 evaluator runs, 4 evaluations | 1.0, 4, 1, 0 |
| Two evaluators named `judge` (strict 0.0, lenient 1.0) | 4 task runs, 1 evaluator runs, 4 evaluations | 1.0, 4, 4, 0 |
| Task raises (`retries=3`, the default) | 4 task runs, 1 evaluator runs, 4 evaluations | 0.25, 4, 4, 0; experiment `errorRate` 0.75 |

| Scenario (c2-c4 of 4 cases) | `evaluate_dataframe` setting | `judge_execution_details` c1-c4 | Scored | Mean |
|---|---|---|---|---|
| Evaluator raises | defaults | COMPLETED, FAILED (11 attempts), DID NOT RUN × 2 | 1 | 1.0 |
| Same | `exit_on_error=False, max_retries=0` | COMPLETED, FAILED × 3 | 1 | 1.0 |
| Evaluator returns `None` | defaults | COMPLETED, FAILED (11 attempts), DID NOT RUN × 2 | 1 | 1.0 |
| Evaluator returns `{"score": None}` | defaults | COMPLETED × 4 | 1 | 1.0 |
| Two evaluators named `judge` | defaults | COMPLETED × 4 (one column) | 4 | 1.0 |

"Mean" for `evaluate_dataframe` is pandas' over the `score` field of the `judge_score` column;
the function returns per-row results and no aggregate.

**Experiments.** An evaluator's exception is caught per case, printed, and stored as an
evaluation with no result and the exception's `repr` as `error`
([`resources/experiments/__init__.py` L2033-L2052](https://github.com/Arize-ai/phoenix/blob/arize-phoenix-client-v3.7.0/packages/phoenix-client/src/phoenix/client/resources/experiments/__init__.py#L2033-L2052)).
The server's annotation summary averages scores with SQL `AVG`, which skips nulls, and reports
`count`, `errorCount` and `scoreCount` next to it
([`dataloaders/experiment_annotation_summaries.py` L67-L114](https://github.com/Arize-ai/phoenix/blob/arize-phoenix-v22.0.0/src/phoenix/server/api/dataloaders/experiment_annotation_summaries.py#L67-L114)).

1. **Evaluator raises.** `run_experiment` returns normally. The printed summary counts only
   evaluations with a result
   ([L1022-L1045](https://github.com/Arize-ai/phoenix/blob/arize-phoenix-client-v3.7.0/packages/phoenix-client/src/phoenix/client/resources/experiments/__init__.py#L1022-L1045)),
   so it says 1 evaluation where 4 were expected, but nothing compares the two. The server's mean
   is 1.0 from 1 of 4, the same as a full run, but the same summary carries `scoreCount` 1 and
   `errorCount` 3, so the gap is visible to anyone who reads them.
2. **Errors tolerated.** That is the only mode for evaluators; there is no option to fail on them.
3. **No value.** Returning `None` is rejected (`ValueError: Unsupported evaluation result type`)
   and recorded like a raise. Returning `{"score": None}` is accepted silently: no error, the
   printed summary says 4 evaluations, and only `scoreCount` 1 of `count` 4 shows that three cases
   have no score.
4. **Same name.** Evaluators are put in a dict keyed by name, so the later one replaces the
   earlier before anything runs
   ([L385-L403](https://github.com/Arize-ai/phoenix/blob/arize-phoenix-client-v3.7.0/packages/phoenix-client/src/phoenix/client/resources/experiments/__init__.py#L385-L403)).
   The strict evaluator never ran: one evaluation per case, all 1.0, "1 evaluator runs", no
   warning. The results cannot show it; only the evaluator list can.

A task that raises is retried (`retries=3`: 4 attempts per case, each printed) and kept as a run
with an `error`; the evaluators then run on its `None` output, so what the evaluation shows depends
on the evaluator (here 0.0, mean 0.25). The task errors do show in the experiment's `errorRate`
0.75.

**`evaluate_dataframe`.** Each (row, evaluator) pair runs through a `SyncExecutor` whose defaults
are `max_retries=10` and `exit_on_error=True`; `evaluate_dataframe` passes neither unless the
caller does
([`evaluators.py` L1538-L1553](https://github.com/Arize-ai/phoenix/blob/arize-phoenix-evals-v3.10.0/packages/phoenix-evals/src/phoenix/evals/evaluators.py#L1538-L1553),
[`executors.py` L485-L491, L519-L573](https://github.com/Arize-ai/phoenix/blob/arize-phoenix-evals-v3.10.0/packages/phoenix-evals/src/phoenix/evals/executors.py#L485-L573)).

1. **Evaluator raises.** With the defaults, the first failing row is attempted 11 times, then the
   executor stops: the remaining rows are `DID NOT RUN`, their score cells are empty, and
   `evaluate_dataframe` returns normally, so the 1 scored row of 4 gives the same 1.0 as a full
   run. Each row's status is in `<evaluator>_execution_details`; apart from one printed
   `Retries exhausted` line, that column is the only record that the run stopped.
2. **Errors tolerated.** `exit_on_error=False` runs every row; failed rows are `FAILED` with
   their exceptions listed, and the score column is still 1 of 4.
3. **No value.** `None` raises `ValueError` inside the evaluator wrapper, so it behaves exactly
   like a raise, including 10 retries of a deterministic error. `{"score": None}` is `COMPLETED`
   with no score.
4. **Same name.** Both evaluators run and write to the same `judge_score` and
   `judge_execution_details` columns; the later one's values replace the earlier's (here 1.0 on
   every row). The docstring says so
   ([`evaluators.py` L1517-L1523](https://github.com/Arize-ai/phoenix/blob/arize-phoenix-evals-v3.10.0/packages/phoenix-evals/src/phoenix/evals/evaluators.py#L1517-L1523)).

Not probed: the Phoenix UI's rendering of these summaries, `async_evaluate_dataframe`, and
annotations logged on traces rather than experiments.

What a gate on Phoenix results needs, from the above: for experiments, `scoreCount` against the
number of expected runs per evaluation name, plus `errorCount` and the experiment's `errorRate`
(the server already computes all three), and a check before the run that evaluator names are
unique. For `evaluate_dataframe`, the `status` of every `*_execution_details` cell and the number
of non-empty scores per column, with evaluator names checked before the run. eval-preflight does
not read Phoenix results yet.

## Logfire

Here Logfire is the destination, not the runner: pydantic-evals emits OpenTelemetry spans while
`Dataset.evaluate` runs, with `logfire.experiment.*` attributes for Logfire's experiment views. So
the question for Logfire is what those spans carry when scoring is incomplete. The probe
([`scripts/research/logfire_probe.py`](../scripts/research/logfire_probe.py), `make research`)
runs pydantic-evals 2.71.0 under `logfire.configure(send_to_logfire=False)` (SDK 6.0.0) with
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` pointed at an OTLP/HTTP receiver on loopback. Logfire adds that
exporter to the same span pipeline as its own
([`config.py` L1328-L1342, L1507, L1559-L1572](https://github.com/pydantic/logfire/blob/v6.0.0/logfire-sdk/logfire/_internal/config.py#L1328-L1572)), so the receiver decodes the
protobuf spans a Logfire project would get; no account, no token, no network. Output, with each
scenario's in-process `EvaluationReport` next to the exported spans:
[`research/logfire-6.0.0.json`](research/logfire-6.0.0.json). Two runs write byte-identical output.
Every cited file is identical in the wheels and the tags `v2.71.0` (pydantic-ai) and `v6.0.0`
(logfire). The Logfire UI itself is not probed.

pydantic-evals emits one `evaluate {name}` span per run, carrying `n_cases` and
`logfire.experiment.metadata` (`n_cases` plus the report's `averages`)
([`dataset.py` L340-L363, L1110-L1145](https://github.com/pydantic/pydantic-ai/blob/v2.71.0/pydantic_evals/pydantic_evals/dataset.py#L1110-L1145)); one `case: {case_name}`
child per case, carrying that case's `scores`, `assertions` and `labels`
([L1209-L1262](https://github.com/pydantic/pydantic-ai/blob/v2.71.0/pydantic_evals/pydantic_evals/dataset.py#L1209-L1262)); and one `evaluator: {evaluator_name}` child per
evaluator call ([`evaluators/_run_evaluator.py` L84-L123](https://github.com/pydantic/pydantic-ai/blob/v2.71.0/pydantic_evals/pydantic_evals/evaluators/_run_evaluator.py#L84-L123)).

| Scenario (c2-c4 of 4 cases) | Experiment span: `averages.scores` | Case span `scores` on c2-c4 | Evaluator spans on c2-c4 |
|---|---|---|---|
| `Judge` raises | `Judge` 1.0 | `{}` | one, status ERROR, `exception` event |
| `Judge` returns `{}` | `Judge` 1.0 | `{}` | one, status UNSET |
| `Judge` attached to c1 only | `Judge` 1.0 | `{}` | none |
| Two `Judge`s, strict 0.0 and lenient 1.0 | `Judge` 0.0, `Judge_2` 1.0 | `Judge` 0.0, `Judge_2` 1.0 | two, both named `Judge` |
| Same, strict raises on c2-c4 | `Judge` 0.75, `Judge_2` 1.0 | `Judge` 1.0 | two named `Judge`, one ERROR |
| Task raises | `Judge` 1.0 | attribute absent; case span ERROR | none |

The experiment span's `n_cases` is 4 in every scenario, and `averages` matches the in-process
report's `averages()` exactly.

1. **Evaluator raises.** Nothing on the experiment span records it: there is no error count and no
   failure list (`logfire.experiment.report_evaluator_failures` is only for report-level
   evaluators), and the span status stays UNSET. The case span has `scores: {}` and no failure
   attribute either; the in-process report's `evaluator_failures` is not exported. The error is
   only on the child evaluator span (status ERROR, an `exception` event with the message). So
   `averages.scores.Judge` is 1.0 from 1 of 4 cases, as in pydantic-evals' own report, and the
   count it came from has to be rebuilt by counting case spans with the key.
2. **Errors tolerated.** Not applicable: pydantic-evals never fails a run on evaluator errors.
3. **No value.** Returning `{}` gives the same experiment and case span attributes as raising, but
   the evaluator span is a clean UNSET with no event. An evaluator attached to c1 only gives the
   same attributes again, with no evaluator span at all on c2-c4. The child spans therefore tell
   the three apart, which the saved report cannot ([dogfood.md, finding 2](dogfood.md)), but only
   for a reader that walks the trace tree.
4. **Same name.** The suffixing of pydantic-evals happens before export, so the spans carry the
   same names as the report, including the shift from
   [pydantic/pydantic-ai#10636](https://github.com/pydantic/pydantic-ai/issues/10636): when the
   strict `Judge` raises on c2-c4, the lenient one's 1.0 is filed as `Judge` on those cases, and the
   experiment span's `Judge` average is 0.75, a mix of two evaluators. Both evaluator spans are
   named `Judge`, so the trace cannot say which result came from which.

A task that raises is recorded on the case span (status ERROR, `exception` event, no `output` or
`scores` attributes) and the case is left out of the averages, so `Judge` is again 1.0 from 1 of
4; only `n_cases` 4 against the number of case spans with scores shows the gap.

Not probed: the Logfire UI and its query API, `repeat` > 1 (which adds
`logfire.experiment.repeat` and `logfire.experiment.source_case_name`), and scores attached to
production traces rather than to an experiment.

What a gate on Logfire data needs, from the above: per score name, the number of case spans
carrying it against `n_cases`; the evaluator spans with status ERROR under each case; and, because
names are suffixed before export, a check before the run that evaluator names are unique.
eval-preflight does not read OTel spans; it reads the pydantic-evals report, which has the same
counts (and the per-case `evaluator_failures` the spans lack).
