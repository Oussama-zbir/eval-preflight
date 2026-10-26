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
| `cases[].*.source` | evaluator id, e.g. `Judge("strict")` (see below). Never the dict key. |
| `cases[].evaluator_failures[]` | a measurement with `value: null` and `error` = `error_message` (prefixed with `error_type` only if pydantic-evals did not already); kind taken from the same evaluator elsewhere in the run, else `score` |
| `failures[]` | a case-run with `task_error` = `error_message` |
| `source_case_name` + name suffix ` [i/n]` | `case_id` = `source_case_name`, `run_index` = `i - 1` |

Evaluator ids are the source's class name plus its serialization arguments, which pydantic-evals
writes as `null` (no non-default arguments), a one-element list (one) or a dict (several). Values
are JSON-encoded with sorted keys: `NonEmpty()`, `Judge("strict")`,
`Judge(model="m", rubric="strict")`. A result or failure without `source` is rejected (exit 2):
its identity cannot be verified, and inferring it from the display key would hide the
mislabelling that `name-collision` exists to catch.

From JSON, `source_version` and `reported_aggregates` are left empty: the file does not record
the producing version, and `report.averages()` needs the in-memory report.

`--format auto` picks this adapter for a JSON object that has `cases` and `failures` lists and no
`"source": "generic"`.
