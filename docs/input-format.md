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
is a usage error (exit 2); pass `--format` explicitly.
