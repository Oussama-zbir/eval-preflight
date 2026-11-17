# /// script
# requires-python = ">=3.11"
# dependencies = ["braintrust==0.51.0"]
# ///
"""Probe how Braintrust reports partial and failed scoring (docs/research-notes.md).

Run with `make research` (equivalently `uv run --no-project scripts/research/braintrust_probe.py`).
No account, no API key and no network: every scenario runs with `no_send_logs`, which the SDK
documents as running the evaluation locally, and every scorer is deterministic.

One `Eval` over four cases `c1`..`c4` (input = expected = case id, the task echoes the input),
with a scorer named `judge` that scores 1.0 on c1:

- `scorer_raises`: `judge` raises on c2-c4.
- `scorer_raises_error_score_handler`: same, with the SDK's `default_error_score_handler`.
- `scorer_returns_none`: `judge` returns `None` on c2-c4.
- `two_scorers_same_name`: two scorers return `Score(name="judge")`; `strict` scores 0.0 and
  `lenient` scores 1.0 on every case.
- `task_raises`: the task raises on c2-c4 (the scorer would score 1.0 everywhere).
- `task_raises_error_score_handler`: same, with `default_error_score_handler`.

Each scenario is run twice, each in its own process:

- `braintrust eval --no-send-logs --jsonl` on the eval file: what a CI gate sees. The probe records
  the exit code, the summary scores the CLI prints (or the number of errors it reports instead),
  and how many "Found exceptions for the following scorers" lines it printed.
- `Eval(..., no_send_logs=True)` in-process: the per-case `scores`, task error and
  `metadata.scorer_errors` keys of the returned results, which the CLI does not print.

Writes docs/research/braintrust-<version>.json. Never hand-edit the output; change this script and
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

VERSION = "0.51.0"
OUT = Path(__file__).resolve().parents[2] / "docs" / "research" / f"braintrust-{VERSION}.json"

# Named eval_*.py so `braintrust eval` would also pick it up from a directory. Under the CLI,
# `Eval(...)` only registers the evaluator; run as a script, it evaluates immediately.
EVAL_FILE = """\
import json
import os
import sys

from braintrust import Eval, Score
from braintrust.framework import default_error_score_handler

SCENARIO = os.environ["PROBE_SCENARIO"]
FAILING = {"c2", "c3", "c4"}


def task(input):
    if SCENARIO.startswith("task_raises") and input in FAILING:
        raise RuntimeError("model timeout")
    return input


def judge(input, output, expected):
    if input in FAILING:
        if SCENARIO.startswith("scorer_raises"):
            raise RuntimeError("judge quota exhausted")
        if SCENARIO == "scorer_returns_none":
            return None
    return 1.0


def strict(input, output, expected):
    return Score(name="judge", score=0.0)


def lenient(input, output, expected):
    return Score(name="judge", score=1.0)


kwargs = {}
if SCENARIO.endswith("_error_score_handler"):
    kwargs["error_score_handler"] = default_error_score_handler

evaluator = dict(
    data=[{"input": f"c{i}", "expected": f"c{i}"} for i in range(1, 5)],
    task=task,
    scores=[strict, lenient] if SCENARIO == "two_scorers_same_name" else [judge],
    **kwargs,
)

if __name__ == "__main__":
    result = Eval("probe", no_send_logs=True, **evaluator)
    rows = [
        {
            "case": row.input,
            "scores": row.scores,
            "task_error": f"{type(row.error).__name__}: {row.error}" if row.error else None,
            "scorer_errors": sorted((row.metadata or {}).get("scorer_errors", {})),
        }
        for row in result.results
    ]
    summary = {name: s["score"] for name, s in result.summary.as_dict()["scores"].items()}
    with open(sys.argv[1], "w") as f:
        json.dump({"rows": rows, "summary_scores": summary}, f)
else:
    Eval("probe", **evaluator)
"""

SCENARIOS = [
    "scorer_raises",
    "scorer_raises_error_score_handler",
    "scorer_returns_none",
    "two_scorers_same_name",
    "task_raises",
    "task_raises_error_score_handler",
]

SCORER_ERROR_LINE = "Found exceptions for the following scorers"


def _env(scenario: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRAINTRUST_")}
    return {**env, "PROBE_SCENARIO": scenario, "NO_COLOR": "1"}


def run_cli(workdir: Path, eval_file: Path, scenario: str) -> dict[str, Any]:
    proc = subprocess.run(
        [
            # The console script, as users run it. `python -m braintrust.cli` ends with
            # `os._exit(1)` on failure, which discards the buffered JSON line.
            str(Path(sys.executable).parent / "braintrust"),
            "eval",
            "--no-send-logs",
            "--jsonl",
            "--no-progress-bars",
            str(eval_file),
        ],
        cwd=workdir,
        env=_env(scenario),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    if len(lines) != 1:
        raise SystemExit(f"{scenario}: expected one JSON line\n{proc.stdout}\n{proc.stderr}")
    (line,) = lines
    printed: dict[str, Any]
    if "errors" in line:
        # The default reporter prints the errors instead of the summary; tracebacks carry
        # absolute paths, so only their count is recorded.
        printed = {"errors_reported": len(line["errors"])}
    else:
        printed = {"summary_scores": {n: s["score"] for n, s in line["scores"].items()}}
    return {
        "exit_code": proc.returncode,
        "printed": printed,
        "scorer_exception_lines": (proc.stdout + proc.stderr).count(SCORER_ERROR_LINE),
    }


def run_in_process(workdir: Path, eval_file: Path, scenario: str) -> dict[str, Any]:
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
        raise SystemExit(f"{scenario}: in-process run failed\n{proc.stdout}\n{proc.stderr}")
    result: dict[str, Any] = json.loads(out.read_text())
    return result


def main() -> None:
    installed = version("braintrust")
    if installed != VERSION:
        raise SystemExit(f"expected braintrust {VERSION}, found {installed}")
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        eval_file = workdir / "eval_probe.py"
        eval_file.write_text(EVAL_FILE)
        scenarios = {
            name: {
                "cli": run_cli(workdir, eval_file, name),
                "in_process": run_in_process(workdir, eval_file, name),
            }
            for name in SCENARIOS
        }
    report = {
        "framework": "braintrust",
        "version": VERSION,
        "generated_by": "scripts/research/braintrust_probe.py",
        "cli": "braintrust eval --no-send-logs --jsonl --no-progress-bars eval_probe.py",
        "scenarios": scenarios,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}")


if __name__ == "__main__":
    main()
