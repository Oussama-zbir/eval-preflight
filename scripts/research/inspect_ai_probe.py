# /// script
# requires-python = ">=3.11"
# dependencies = ["inspect-ai==0.3.289"]
# ///
"""Probe how Inspect AI reports partial and failed scoring (docs/research-notes.md).

Run with `make research` (equivalently
`uv run --no-project scripts/research/inspect_ai_probe.py`). No API key: the task uses
Inspect's `mockllm/model`, and every scorer is deterministic.

Four samples `c1`..`c4`. Each scenario differs only in its scorer or error setting:

- `scorer_raises`: the scorer raises on c2-c4 (default `fail_on_error`).
- `scorer_raises_no_fail_on_error`: same scorer, `--no-fail-on-error`.
- `scorer_raises_fail_on_error_0.8`: same scorer, `--fail-on-error 0.8` (3/4 errors, under 80%).
- `scorer_returns_none`: the scorer returns `None` on c2-c4.
- `scorer_returns_nan`: the scorer returns `Score(value=nan)` on c2-c4.
- `two_scorers_same_name`: `judge("strict")` scores only c1 (0.0, `None` elsewhere) and
  `judge("lenient")` scores 1.0 everywhere.

`scorer_raises_eval_set` repeats `scorer_raises` with `inspect eval-set --retry-attempts 0`.

Each scenario runs through the `inspect eval` (or `eval-set`) CLI, whose exit code is what a CI
step sees, and the log is read back with `read_eval_log`. Writes
docs/research/inspect-ai-0.3.289.json. Never hand-edit the output; change this script and rerun.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from inspect_ai.log import read_eval_log

VERSION = "0.3.289"
OUT = Path(__file__).resolve().parents[2] / "docs" / "research" / f"inspect-ai-{VERSION}.json"

TASK_FILE = """\
import math

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, mean, scorer
from inspect_ai.solver import generate

SAMPLES = [Sample(id=f"c{i}", input="hi", target="x") for i in range(1, 5)]


@scorer(metrics=[mean()])
def flaky_judge():
    async def score(state, target):
        if state.sample_id != "c1":
            raise RuntimeError("judge quota exhausted")
        return Score(value=1.0)

    return score


@scorer(metrics=[mean()])
def judge_none():
    async def score(state, target):
        return Score(value=1.0) if state.sample_id == "c1" else None

    return score


@scorer(metrics=[mean()])
def judge_nan():
    async def score(state, target):
        return Score(value=1.0 if state.sample_id == "c1" else math.nan)

    return score


@scorer(metrics=[mean()])
def judge(rubric: str):
    async def score(state, target):
        if rubric == "strict":
            return Score(value=0.0) if state.sample_id == "c1" else None
        return Score(value=1.0)

    return score


@task
def raises():
    return Task(dataset=SAMPLES, solver=generate(), scorer=flaky_judge())


@task
def returns_none():
    return Task(dataset=SAMPLES, solver=generate(), scorer=judge_none())


@task
def returns_nan():
    return Task(dataset=SAMPLES, solver=generate(), scorer=judge_nan())


@task
def same_name():
    return Task(dataset=SAMPLES, solver=generate(), scorer=[judge("strict"), judge("lenient")])
"""

SCENARIOS: list[tuple[str, str, str, list[str]]] = [
    ("scorer_raises", "eval", "raises", []),
    ("scorer_raises_eval_set", "eval-set", "raises", ["--retry-attempts", "0"]),
    ("scorer_raises_no_fail_on_error", "eval", "raises", ["--no-fail-on-error"]),
    ("scorer_raises_fail_on_error_0.8", "eval", "raises", ["--fail-on-error", "0.8"]),
    ("scorer_returns_none", "eval", "returns_none", []),
    ("scorer_returns_nan", "eval", "returns_nan", []),
    ("two_scorers_same_name", "eval", "same_name", []),
]


def _value(value: Any) -> Any:
    # JSON has no NaN; record it as a string so the file stays strict JSON.
    return "nan" if isinstance(value, float) and value != value else value


def run(workdir: Path, name: str, subcommand: str, task: str, flags: list[str]) -> dict[str, Any]:
    log_dir = workdir / f"logs-{name}"
    command = [
        sys.executable,
        "-m",
        "inspect_ai",
        subcommand,
        f"task.py@{task}",
        "--model",
        "mockllm/model",
        "--log-dir",
        str(log_dir),
        "--display",
        "none",
        *flags,
    ]
    env = {**os.environ, "INSPECT_LOG_FORMAT": "eval"}
    proc = subprocess.run(command, cwd=workdir, env=env, check=False, capture_output=True)
    (log_path,) = log_dir.glob("*.eval")
    log = read_eval_log(str(log_path))

    results = None
    if log.results is not None:
        results = {
            "total_samples": log.results.total_samples,
            "completed_samples": log.results.completed_samples,
            "scores": [
                {
                    "name": s.name,
                    "metrics": {k: _value(m.value) for k, m in s.metrics.items()},
                    "scored_samples": s.scored_samples,
                    "unscored_samples": s.unscored_samples,
                }
                for s in log.results.scores
            ],
        }
    return {
        "command": ["inspect", *command[3:5], *flags],
        "exit_code": proc.returncode,
        "status": log.status,
        "error": None if log.error is None else log.error.message,
        "results": results,
        "samples": {
            str(s.id): {
                "error": None if s.error is None else s.error.message,
                "scores": {k: _value(v.value) for k, v in (s.scores or {}).items()},
            }
            for s in sorted(log.samples or [], key=lambda s: str(s.id))
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "task.py").write_text(TASK_FILE)
        report = {
            "framework": "inspect-ai",
            "version": VERSION,
            "generated_by": "scripts/research/inspect_ai_probe.py",
            "scenarios": {
                name: run(workdir, name, subcommand, task, flags)
                for name, subcommand, task, flags in SCENARIOS
            },
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}")


if __name__ == "__main__":
    main()
