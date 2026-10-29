# Generic input format

The generic format is the canonical model ([SPEC.md](../SPEC.md) §5) with each measurement's
evaluator flattened into `evaluator_id`, `display_name` and `kind`. Any framework can be converted
into it. Parsing is strict: unknown fields are an error, so a typo does not silently drop data.

## JSON document

```json
{
  "name": "name_shift",
  "source": "generic",
  "source_version": null,
  "reported_aggregates": null,
  "cases": [
    {"case_id": "c1", "run_index": 0, "task_error": null,
     "measurements": [
       {"evaluator_id": "Judge(rubric='strict')", "display_name": "Judge",
        "kind": "score", "value": 0.0, "error": null}
     ]}
  ]
}
```

`source` must be `"generic"`. `source_version` and `reported_aggregates` are optional.

## JSONL

One case result per line, same shape as an entry of `cases`. Blank lines are ignored. The run
name is the file name without its extension.

```json
{"case_id": "c1", "run_index": 0, "task_error": null, "measurements": [{"evaluator_id": "Judge(rubric='strict')", "display_name": "Judge", "kind": "score", "value": 0.0, "error": null}]}
```

## Fields

| Field | Type | Meaning |
|---|---|---|
| `case_id` | string, required | Stable across runs. For repeats, the original case name. |
| `run_index` | int ≥ 0, default 0 | 0-based repeat index. `(case_id, run_index)` must be unique. |
| `task_error` | string or null | The task under test raised; no measurements expected. |
| `measurements[].evaluator_id` | string, required | Stable evaluator identity, e.g. `Judge(rubric='strict')`. Never derive it from the display name. |
| `measurements[].display_name` | string, required | The name the framework reported, e.g. `Judge` or `Judge_2`. |
| `measurements[].kind` | `score` \| `assertion` \| `label` | |
| `measurements[].value` | number, bool, string or null | `null` when the evaluator produced nothing. |
| `measurements[].error` | string or null | Set when the evaluator failed on this case-run. |

## Detection

`--format auto` (the default) treats the file as generic when it is a JSON object with
`"source": "generic"`, or when its first JSON value is an object with a `case_id`. Anything else
is checked against the pydantic-evals shape below, then is a usage error (exit 2); pass
`--format` explicitly.

# pydantic-evals report (JSON)

The file written by `TypeAdapter(EvaluationReport).dump_json(report, by_alias=True)`. The adapter
reads only the fields below, ignores the rest (inputs, outputs, durations, stack traces) and does
not need pydantic-evals installed. Verified against reports generated with pydantic-evals 2.61.0
(`make fixtures`; outputs in `tests/fixtures/pydantic_evals/`).

| Report field | Becomes |
|---|---|
| `dataset_name` (else `name`, the task name) | `EvalRun.name` |
| `cases[].scores` / `assertions` / `labels` | one measurement each, kind `score` / `assertion` / `label`; `display_name` is the dict key |
| `cases[].*.source` + `name` | evaluator id, e.g. `Judge(rubric='strict')` or `Checks()[fmt]` (see below). Never the dict key. |
| `cases[].evaluator_failures[]` | a measurement with `value: null` and `error` = `error_message` (prefixed with `error_type` only if pydantic-evals did not already); kind taken from the same evaluator elsewhere in the run, else `score` |
| `failures[]` | a case-run with `task_error` = `error_message` |
| `source_case_name` + name suffix ` [i/n]` | `case_id` = `source_case_name`, `run_index` = `i - 1` |

Evaluator ids are `Name(key=repr(value), ...)` with keys sorted at every level, built from the
source's class name and serialization arguments: `NonEmpty()`, `Judge(model='m', rubric='strict')`.

pydantic-evals serializes only non-default fields (`BaseEvaluator.as_spec`): none as `null`,
several as a dict, and a single one as a dict too, **except** when that field is the evaluator's
first dataclass field, which it writes as a one-element list without the field name
(`"arguments": ["strict"]`). The name is not in the report, JSON or in-memory, so the id renders
the value positionally, `Judge('strict')`, the same call that reconstructs the evaluator. It
never invents a key. The consequence: the same evaluator gets `Judge('strict')` from a
pydantic-evals report and whatever id you choose (e.g. `Judge(rubric='strict')`) in a generic file;
do not compare runs across the two formats by id.

Multi-output evaluators: a result's `name` is the evaluator's own name for a scalar output and
the dict key for a named output. When it differs from the source name, the id gets the output
name appended, `Checks()[fmt]`, so each output is its own evaluator and the outputs of one
evaluator do not trip `name-collision`. The display name stays the section key, which carries
pydantic-evals' per-case `_2` suffixes. A failure carries the evaluator's own name, so a failed
scalar evaluator shares its results' id, while a failed multi-output evaluator appears under the
bare source id (its outputs are unknown when it raises).

A result or failure without `source` is rejected (exit 2): its identity cannot be verified, and
inferring it from the display key would hide the mislabelling that `name-collision` exists to
catch.

From JSON, `source_version` and `reported_aggregates` are left empty: the file does not record
the producing version, and `report.averages()` needs the in-memory report.

## In-memory `EvaluationReport`

```python
from eval_preflight import check_pydantic_evals

report = dataset.evaluate_sync(task)
result = check_pydantic_evals(report)   # or from_pydantic_evals(report) -> EvalRun
result.raise_if_failed()
```

Needs the optional extra: `pip install 'eval-preflight[pydantic-evals]'` (Python ≥ 3.11, tested
with pydantic-evals 2.61.0). The JSON path above never imports pydantic-evals.

The adapter reads the same fields from the report's attributes, so cases, measurements and ids
are identical to loading the report's JSON dump (tested for every golden scenario). Inputs and
outputs are never serialized. Two things only the live report knows are added:

- `reported_aggregates` from `report.averages()`: scores and metrics by display name, plus the
  assertion pass rate under `assertions`. Labels are distributions and are left out. Metrics are
  not measurements, so `aggregation-consistency` reports them as WARN "cannot be checked".
- `source_version` from the installed pydantic-evals.

`--format auto` picks this adapter for a JSON object that has `cases` and `failures` lists and no
`"source": "generic"`.
