# Dogfooding on two public pydantic-evals examples

eval-preflight run on two examples that the pydantic-evals maintainers publish, rather than
on fixtures written to show off its checks. Every number below comes from the committed reports
in [`tests/fixtures/dogfood/`](../tests/fixtures/dogfood/) and is pinned by
[`tests/test_dogfood.py`](../tests/test_dogfood.py).

| Example | Source | Verdict |
|---|---|---|
| `title_case` | "Simple Validation" from the [pydantic-evals docs](https://pydantic.dev/docs/ai/evals/examples/simple-validation/), copied verbatim | PASS (exit 0) |
| `time_range` | `pydantic_ai_examples.evals` from the `pydantic-ai-examples` 2.66.0 wheel, run as in `example_03_unit_testing.py` | FAIL (exit 1): 9 failures, 1 warning |

Reproduce with `make dogfood` (pydantic-evals and pydantic-ai-slim 2.66.0; the examples wheel is
checked against its PyPI sha256). Two runs write byte-identical reports.

## How the time-range example was run

The example's agent, `get_current_time` tool, custom evaluators and `time_range_v2.yaml` dataset are
used unchanged. No API key is used, so the agent model and the `LLMJudge` model are pydantic-ai
`FunctionModel`s: the agent calls `get_current_time`, then answers every case with that case's own
`expected_output`, and the judge passes everything. This is a perfect model. Every finding below
therefore comes from the dataset and evaluator design, not from model quality.

## Findings

### 1. A case-level judge takes the dataset judge's name (true positive)

The dataset has a dataset-wide `LLMJudge` (a friendly-style rubric) and a second `LLMJudge` attached
only to case "Ambiguous mention" (an early-May rubric). On that case, pydantic-evals files the
case-level judge as `LLMJudge` and the dataset-wide judge as `LLMJudge_2`. On the other nine cases
`LLMJudge` is the dataset-wide judge.

```
FAIL  name-collision  "LLMJudge" → LLMJudge('Ensure the explanation ...') on Single day mention, ... (+4 more); LLMJudge('We want to interpret conflicting references ...') on Ambiguous mention
FAIL  name-collision  LLMJudge('Ensure the explanation ...') → "LLMJudge" on Single day mention, ... (+4 more); "LLMJudge_2" on Ambiguous mention
```

The report's `LLMJudge` column and its average therefore mix two rubrics. No evaluator failed here,
so this is a second way into the naming scheme behind
[pydantic/pydantic-ai#10636](https://github.com/pydantic/pydantic-ai/issues/10636), which needs a
failure to shift names. The same check also reports that `IsInstance` means
`IsInstance('TimeRangeBuilderSuccess')` on seven cases and `IsInstance('TimeRangeBuilderError')` on
three. That one is harmless, because both ask whether the output has the expected type, but it is
still one column holding two evaluators.

### 2. Coverage fails on evaluators that are partial by design (false positives)

Six `evaluator-coverage` FAILs, none of which is a lost result:

- four evaluators attached to specific cases: the two `IsInstance` variants (7/10 and 3/10),
  `AgentCalledTool` (1/10) and the case-level `LLMJudge` (1/10);
- the two outputs of `ValidateTimeRange` (7/10 each), which returns `{}` for error outputs
  ("No evaluation needed for errors").

A pydantic-evals report records results, not which evaluators were attached to which case. So
eval-preflight cannot tell "not attached here" from "attached and lost". The workaround,
`--min-coverage 0.1`, would also hide a judge that silently scored 1 case in 10, which is the
failure the check exists for ([#7928](https://github.com/pydantic/pydantic-ai/issues/7928)). This is
the main product gap the dogfood found. It is recorded in [BACKLOG.md](../BACKLOG.md) and needs a
design decision before it is built.

### 3. The assertion pass rate depends on the estimator (true positive, no verdict change)

Cases carry between 3 and 6 assertions. Pooled, 42 of 46 assertions pass (0.913). The mean of
per-case pass rates is 0.923. For a single run, pydantic-evals' `averages()` reports the pooled
number. `example_03_unit_testing.py` gates on `> 0.9`, which both estimators clear here, so this run
only gets a WARN. With a perfect model the margin is 1.3 points, because 4 assertions fail on the
reference answers themselves: "Far future mention" (January 3050, a 31-day window) fails both
`ValidateTimeRange` assertions, "Range from speech" (December 2023, after the case's `now`) fails
`window_is_not_in_the_future`, and `AgentCalledTool` is the fourth (finding 4).

### 4. Missed: a span query that can never match (false negative)

`AgentCalledTool` returned `False` even though the stub model did call `get_current_time`. The
example's evaluator queries spans named `agent run` and `running tool`. Those are pydantic-ai's
version-2 instrumentation names. 2.66.0 defaults to version 5 (`DEFAULT_INSTRUMENTATION_VERSION`
in `pydantic_ai/_instrumentation.py`), which names the spans `invoke_agent {agent}` and
`execute_tool {tool}`. So the evaluator is `False` on every run, whatever the model does. The
[agentic evaluator docs](https://pydantic.dev/docs/ai/evals/evaluators/agentic/) already match tool
spans under both names (`running tool` or `execute_tool {name}`).

eval-preflight passes this evaluator: a well-formed `False` is complete, correctly attributed and
correctly averaged. Catching it would take a check on evaluator semantics, which is outside what
eval-preflight claims to do (see the README's Limitations). On a longer dataset, `constant-output`
would not flag it either, since it covers score and label evaluators, not assertions.

### 5. The clean example passes, though its own docs misreport the numbers

`title_case` passes every check. That is the correct verdict, even though `has_capitals` fails on 2
of 8 cases (`""` and `"Don'T Stop Believin'"` contain no `H`). The real assertion pass rate is
30/32 = 93.75%. The docs page's "Expected Output" shows 96.9% and "All tests passed!". eval-preflight
checks that the numbers describe the run, not that they are good or match the docs.

## What changed in eval-preflight

Nothing in the checks. Finding 2 is a verdict-changing design question (see BACKLOG.md), and the
repository rules say to stop and ask rather than guess.
