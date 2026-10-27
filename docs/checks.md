# Checks

Every check returns findings with a severity (`PASS`, `WARN`, `FAIL`), a one-line message and
structured `details`. The overall verdict is `FAIL` if any finding fails, `WARN` if only warnings,
else `PASS`. Defaults are deliberately strict.

Terms: a **case-run** is the pair `(case_id, run_index)`. An **eligible** case-run is one whose
task did not fail. Evaluator identity is the evaluator **id**, never its display name. When a run
has repeats, case-runs are labelled `case_id[run_index]`; otherwise just `case_id`.

Implemented: checks 1–4 (0.0.1) and 5 (unreleased). Checks 6–7 (`constant-output`,
`baseline-comparability`) are specified in [SPEC.md](../SPEC.md) §6 and not built yet.

## 1. `task-failures`

**Detects** case-runs where the task under test raised (`task_error` is set).

**Why it matters.** A failed task produces no measurements, so every evaluator average silently
ignores it. The headline score then describes a subset of the dataset.

**Default.** FAIL if the failure rate is above `--max-task-failure-rate` (0.0). A rate equal to the
threshold passes. The message always reports `n/N` over all case-runs. A run with no case-runs at
all fails: there is nothing to trust.

```
PASS  task-failures           0/4
FAIL  task-failures           1/4 case-runs (25%) raised: TimeoutError: model took too long
```

`details`: `failed`, `total`, `rate`, `threshold`, `failed_case_runs`, `most_common_error`.

## 2. `evaluator-coverage`

**Detects**, per evaluator id, how many eligible case-runs it produced a non-null value for.
`0`, `0.0` and `false` are values; only `null` (or no measurement at all) is missing.

**Why it matters.** In pydantic-evals, a judge that scores 1 case of 4 and raises on the rest
reports the same average as one that scored all 4
([pydantic/pydantic-ai#7928](https://github.com/pydantic/pydantic-ai/issues/7928)). A threshold
gate then passes on evidence that does not exist.

**Default.** FAIL for any evaluator whose coverage is below `--min-coverage` (1.0); coverage equal
to the threshold passes. One finding per evaluator, always with `n/N (pct)`. Percentages are
truncated, never rounded up, so a partial count never reads `100%`. An evaluator with no eligible
case-runs fails, and so does a run in which no evaluator measured anything.

```
FAIL  evaluator-coverage      Judge(rubric='strict') scored 1/4 case-runs (25%)
PASS  evaluator-coverage      Judge(rubric='lenient') scored 4/4 case-runs (100%)
```

`details`: `evaluator_id`, `covered`, `eligible`, `coverage`, `threshold`, `uncovered_case_runs`.

## 3. `evaluator-errors`

**Detects**, per evaluator id, eligible case-runs where the evaluator reported an `error`. A
case-run with several errors from the same evaluator counts once.

**Why it matters.** An evaluator error is not a low score. Coverage tells you a value is missing;
this check tells you why, and how often.

**Default.** FAIL if the error rate is above `--max-evaluator-error-rate` (0.0); equal passes. The
message names the most common error message (ties go to the first seen).

```
FAIL  evaluator-errors        Judge(rubric='strict') errored on 3/4: RuntimeError: judge quota exhausted
```

`details`: `evaluator_id`, `errored`, `eligible`, `rate`, `threshold`, `errored_case_runs`,
`error_counts`, `most_common_error`.

## 4. `name-collision`

**Detects** display names that do not map one-to-one onto evaluator ids, across the whole run:

- (a) one display name carries values from two or more evaluator ids;
- (b) one evaluator id reports values under two or more display names.

Only measurements that carry a value count. A failed evaluator keeps its display name, but nothing
was filed under it, so it cannot shift a score.

**Why it matters.** In pydantic-evals, two evaluators with the same default name are disambiguated
with `_2`, `_3` suffixes per case, counting only evaluators that succeeded. When the first one fails
on a case, the second one's value is stored under the first one's name
([pydantic/pydantic-ai#10636](https://github.com/pydantic/pydantic-ai/issues/10636)). The average
for `"Judge"` then mixes two different judges.

**Default.** Always FAIL; there is no threshold. One finding per ambiguous name or id, showing the
mapping. Case lists longer than five are truncated in the message (`(+N more)`) but complete in
`details.mapping`.

```
FAIL  name-collision          "Judge" → Judge(rubric='strict') on c1; Judge(rubric='lenient') on c2, c3, c4
FAIL  name-collision          Judge(rubric='lenient') → "Judge_2" on c1; "Judge" on c2, c3, c4
```

`details`: `kind` (`display_name_to_ids` or `id_to_display_names`), `display_name` or
`evaluator_id`, `mapping`.

## 5. `aggregation-consistency`

**Detects** two problems with averages:

- the two common estimators disagree. Over the numeric values of eligible case-runs, the
  **pooled mean** averages every value; the **mean of per-case means** averages within each
  `case_id` (across repeats) first. They differ when cases contribute unequal numbers of values:
  repeats where some runs lost a value, or cases with different numbers of assertions. Checked per
  evaluator id (`score` and `assertion` kinds; `label` is not numeric) and for all assertions as a
  group, since frameworks report a single assertion pass rate;
- a reported headline number (`reported_aggregates`) cannot be reproduced from the raw results by
  either estimator.

Booleans count as 1 and 0. Errored or missing values are excluded from both estimators, which is
exactly why coverage (check 2) matters: an average can be reproducible and still describe one case
of four.

**Why it matters.** pydantic-evals averages a single run by pooling every value under a display
name, and the pass rate of all assertions together; for repeated runs, `averages()` averages each
case's own summary instead (`ReportCaseAggregate.average` and `EvaluationReport.averages` in
`pydantic_evals/reporting/__init__.py`). The same data can therefore produce different headline
numbers depending on whether `repeat` was set. In SPEC scenario C, case `a` has one passing
assertion and case `b` three failing ones, repeated twice: pooled 2/8 = 0.25, mean of per-case
means 0.5.

**Default.** WARN per evaluator (or the assertion group) when the estimators differ by more than
`--aggregation-tolerance` (1e-9, used as both relative and absolute tolerance); `--strict-aggregation`
makes it a FAIL. For each reported aggregate, keyed by display name (`assertions` falls back to
the assertion group when no evaluator has that display name): PASS stating which estimator
reproduces it and from how many of the eligible cases; FAIL when it matches neither; WARN when
no numeric values were filed under that name, because there is nothing to check it against. A
run with no numeric values produces no findings.

```
WARN  aggregation-consistency all assertions: pooled mean 0.25 vs mean of per-case means 0.5
PASS  aggregation-consistency reported "assertions" = 0.5 reproduced as the mean of per-case means from 2 of 2 cases (pooled mean: 0.25)
PASS  aggregation-consistency reported "FlakyScore" = 1 reproduced from 1 of 4 cases
FAIL  aggregation-consistency reported "e" = 0.9 matches neither pooled mean 0.5 nor mean of per-case means 0.5
```

`details` for estimator findings: `evaluator_id` (or `group: "assertions"`), `pooled`,
`mean_of_cases`, `values`, `cases`, `tolerance`. For reported aggregates: `reported_key`,
`reported`, `pooled`, `mean_of_cases`, `reproduced_by` (`pooled`, `mean_of_cases`, `both` or
`null`), `cases_with_values`, `eligible_cases`, `tolerance`.
