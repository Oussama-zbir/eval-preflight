# /// script
# requires-python = ">=3.11"
# dependencies = ["langsmith==0.14.9", "pandas==2.3.3"]
# ///
"""Probe how LangSmith's `evaluate()` reports partial and failed scoring (docs/research-notes.md).

Run with `make research` (equivalently `uv run --no-project scripts/research/langsmith_probe.py`).
No account, no API key and no network: every scenario runs `evaluate(..., upload_results=False)`
on an in-memory list of examples, with a client pointed at a closed local port so that nothing
can leave the machine, and every evaluator is deterministic.

0.14.9 is pinned because it is the latest release with a tag on GitHub, so the cited source
lines can link to it. 0.15.0 (PyPI, 2026-11-17, untagged) changes only formatting in
`langsmith/evaluation/`.

One `evaluate()` over four examples `c1`..`c4` (input = reference = case id, the target echoes
the input), with an exact-match evaluator returning `{"key": "judge", "score": 1.0}` on c1:

- `evaluator_raises`: `judge` raises on c2-c4.
- `lambda_evaluator_raises`: same evaluator written as a lambda.
- `evaluator_returns_none`: `judge` returns `None` on c2-c4.
- `evaluator_returns_score_none`: `judge` returns `{"key": "judge", "score": None}` on c2-c4.
- `two_evaluators_same_key`: `strict` returns key `judge` with 0.0 and `lenient` key `judge`
  with 1.0 on every case.
- `target_raises`: the target raises on c2-c4 (`error_handling="log"`, the default).
- `target_raises_error_handling_ignore`: same, with `error_handling="ignore"`.

For each scenario, run in its own process, the probe records whether `evaluate()` raised, the
rows of the returned `ExperimentResults` (run error, and each evaluation result's key, score,
error flag and comment), the `feedback.*` columns of `to_pandas()` and their pandas means, and
how many error lines LangSmith logged. `evaluate()` prints no summary of its own when results
are not uploaded.

Writes docs/research/langsmith-<version>.json. Never hand-edit the output; change this script and
rerun.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any

VERSION = "0.14.9"
OUT = Path(__file__).resolve().parents[2] / "docs" / "research" / f"langsmith-{VERSION}.json"

EVAL_FILE = """\
import json
import logging
import math
import os
import sys
import uuid
from datetime import datetime, timezone

from langsmith import Client
from langsmith.evaluation import evaluate
from langsmith.schemas import Example

SCENARIO = os.environ["PROBE_SCENARIO"]
FAILING = {"c2", "c3", "c4"}


def target(inputs):
    if SCENARIO.startswith("target_raises") and inputs["case"] in FAILING:
        raise RuntimeError("model timeout")
    return {"answer": inputs["case"]}


def judge(inputs, outputs, reference_outputs):
    if inputs["case"] in FAILING:
        if SCENARIO == "evaluator_raises":
            raise RuntimeError("judge quota exhausted")
        if SCENARIO == "evaluator_returns_none":
            return None
        if SCENARIO == "evaluator_returns_score_none":
            return {"key": "judge", "score": None}
    return {"key": "judge", "score": float(outputs["answer"] == reference_outputs["answer"])}


def failing_judge(inputs):
    if inputs["case"] in FAILING:
        raise RuntimeError("judge quota exhausted")
    return {"key": "judge", "score": 1.0}


def strict(inputs, outputs, reference_outputs):
    return {"key": "judge", "score": 0.0}


def lenient(inputs, outputs, reference_outputs):
    return {"key": "judge", "score": 1.0}


EVALUATORS = {
    "lambda_evaluator_raises": [lambda inputs: failing_judge(inputs)],
    "two_evaluators_same_key": [strict, lenient],
}

created = datetime(2026, 1, 1, tzinfo=timezone.utc)
dataset_id = uuid.UUID(int=1)
data = [
    Example(
        id=uuid.UUID(int=100 + i),
        dataset_id=dataset_id,
        created_at=created,
        inputs={"case": f"c{i}"},
        outputs={"answer": f"c{i}"},
    )
    for i in range(1, 5)
]

errors_logged = {"evaluator": 0, "target": 0}


class Count(logging.Handler):
    def emit(self, record):
        message = record.getMessage()
        if message.startswith("Error running evaluator"):
            errors_logged["evaluator"] += 1
        elif message.startswith("Error running target function"):
            errors_logged["target"] += 1


logging.getLogger("langsmith").addHandler(Count())

kwargs = {}
if SCENARIO.endswith("_error_handling_ignore"):
    kwargs["error_handling"] = "ignore"

# Port 9 (discard) on loopback is closed: the client's metadata request fails locally.
client = Client(api_url="http://127.0.0.1:9", api_key="probe-no-network")
try:
    results = evaluate(
        target,
        data=data,
        evaluators=EVALUATORS.get(SCENARIO, [judge]),
        upload_results=False,
        max_concurrency=0,
        client=client,
        **kwargs,
    )
except Exception as e:
    report = {"raised": f"{type(e).__name__}: {e}"}
else:
    rows = []
    for row in results:
        rows.append({
            "case": row["example"].inputs["case"],
            "run_error": row["run"].error.strip().splitlines()[-1] if row["run"].error else None,
            "results": [
                {
                    "key": r.key,
                    "score": r.score,
                    "error": bool((r.extra or {}).get("error")),
                    "comment": r.comment,
                }
                for r in row["evaluation_results"]["results"]
            ],
        })
    df = results.to_pandas().sort_values("inputs.case")

    def column(name):
        scores = df[name].astype(float)
        mean = scores.mean()
        return {
            "values": [None if v is None or (isinstance(v, float) and math.isnan(v)) else v
                       for v in df[name].tolist()],
            "mean": None if math.isnan(mean) else mean,
            "count": int(scores.count()),
        }

    report = {
        "raised": None,
        "rows": sorted(rows, key=lambda r: r["case"]),
        "to_pandas": {
            "rows": len(df),
            "feedback_columns": {
                c: column(c) for c in sorted(c for c in df.columns if c.startswith("feedback."))
            },
        },
    }
report["errors_logged"] = errors_logged
with open(sys.argv[1], "w") as f:
    json.dump(report, f)
"""

SCENARIOS = [
    "evaluator_raises",
    "lambda_evaluator_raises",
    "evaluator_returns_none",
    "evaluator_returns_score_none",
    "two_evaluators_same_key",
    "target_raises",
    "target_raises_error_handling_ignore",
]


def _env(scenario: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LANGSMITH_", "LANGCHAIN_"))}
    return {**env, "PROBE_SCENARIO": scenario, "LANGSMITH_TRACING": "false"}


def run(workdir: Path, eval_file: Path, scenario: str) -> dict[str, Any]:
    out = workdir / f"{scenario}.json"
    proc = subprocess.run(
        [sys.executable, "-I", str(eval_file), str(out)],
        cwd=workdir,
        env=_env(scenario),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0 or not out.exists():
        raise SystemExit(f"{scenario}: probe process failed\n{proc.stdout}\n{proc.stderr}")
    result: dict[str, Any] = json.loads(out.read_text())
    return result


def main() -> None:
    installed = version("langsmith")
    if installed != VERSION:
        raise SystemExit(f"expected langsmith {VERSION}, found {installed}")
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        eval_file = workdir / "probe_eval.py"
        eval_file.write_text(EVAL_FILE)
        scenarios = {name: run(workdir, eval_file, name) for name in SCENARIOS}
    report = {
        "framework": "langsmith",
        "version": VERSION,
        "generated_by": "scripts/research/langsmith_probe.py",
        "call": "evaluate(target, data=examples, evaluators=..., upload_results=False)",
        "scenarios": scenarios,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}")


if __name__ == "__main__":
    main()
