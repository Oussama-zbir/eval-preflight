# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["ragas==0.4.4"]
# ///
# <3.14: ragas needs scikit-network, which has no 3.14 wheel (0.33.5); uv would compile it.
"""Probe how ragas reports partial and failed scoring (docs/research-notes.md).

Run with `make research` (equivalently `uv run --no-project scripts/research/ragas_probe.py`).
No API key and no network: every metric is deterministic, no LLM or embeddings are configured,
and analytics are switched off with `RAGAS_DO_NOT_TRACK`.

Four cases `c1`..`c4`. ragas 0.4.4 has two ways to score a dataset, and both are probed.

`ragas.evaluate()` (deprecated in 0.4 in favour of `@experiment`, still documented) with a custom
`SingleTurnMetric` named `judge` that scores 1.0 on c1:

- `evaluate_metric_raises`: the metric raises on c2-c4 (default `raise_exceptions=False`).
- `evaluate_metric_raises_raise_exceptions`: same, with `raise_exceptions=True`.
- `evaluate_metric_returns_none`: the metric returns `None` on c2-c4.
- `evaluate_metric_returns_nan`: the metric returns NaN on c2-c4.
- `evaluate_two_metrics_same_name`: two metrics named `judge`; `strict` scores 0.0 and `lenient`
  scores 1.0 on every case.

`@experiment` over a local CSV dataset, with a `@numeric_metric` named `judge`; the experiment
function awaits `metric.ascore()` and returns `{"case_id", "judge": result.value, "reason":
result.reason}` per row:

- `experiment_metric_raises`: the metric raises on c2-c4.
- `experiment_metric_returns_none`: the metric returns `None` on c2-c4.
- `experiment_task_raises`: the experiment function itself raises on c2-c4.
- `experiment_task_returns_none`: the experiment function returns `None` on c2-c4.

Each scenario runs in its own Python process; the probe records whether the call raised, the
result (`repr(result)` and `result.scores` for `evaluate()`; the saved CSV for `@experiment`,
plus pandas' default `mean()` of its `judge` column), and how many error lines ragas printed or
logged. Writes docs/research/ragas-<version>.json. Never hand-edit the output; change this script
and rerun.
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

VERSION = "0.4.4"
OUT = Path(__file__).resolve().parents[2] / "docs" / "research" / f"ragas-{VERSION}.json"

CHILD = """\
import asyncio
import json
import math
import sys
import typing as t
import warnings
from dataclasses import dataclass, field
from pathlib import Path

warnings.simplefilter("ignore")

SCENARIO, OUT, ROOT = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])


def clean(value):
    # JSON has no NaN; record it as a string so the output stays valid and diffable.
    if isinstance(value, float) and math.isnan(value):
        return "nan"
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def run_evaluate():
    from ragas import EvaluationDataset, evaluate
    from ragas.dataset_schema import SingleTurnSample
    from ragas.metrics.base import MetricType, SingleTurnMetric

    @dataclass
    class Judge(SingleTurnMetric):
        # Not called `mode`: ragas keys a metric with a `mode` attribute as `name(mode=...)`.
        name: str = "judge"
        behaviour: str = "raise"
        _required_columns: t.Dict[MetricType, t.Set[str]] = field(
            default_factory=lambda: {MetricType.SINGLE_TURN: {"user_input", "response"}}
        )

        def init(self, run_config):
            pass

        async def _single_turn_ascore(self, sample, callbacks):
            if self.behaviour == "strict":
                return 0.0
            if sample.user_input != "c1":
                if self.behaviour == "raise":
                    raise RuntimeError("judge quota exhausted")
                if self.behaviour == "none":
                    return None
                if self.behaviour == "nan":
                    return float("nan")
            return 1.0

    metrics = {
        "evaluate_metric_raises": ([Judge(behaviour="raise")], {}),
        "evaluate_metric_raises_raise_exceptions": (
            [Judge(behaviour="raise")],
            {"raise_exceptions": True},
        ),
        "evaluate_metric_returns_none": ([Judge(behaviour="none")], {}),
        "evaluate_metric_returns_nan": ([Judge(behaviour="nan")], {}),
        "evaluate_two_metrics_same_name": (
            [Judge(behaviour="strict"), Judge(behaviour="lenient")],
            {},
        ),
    }
    chosen, kwargs = metrics[SCENARIO]
    dataset = EvaluationDataset(
        samples=[SingleTurnSample(user_input=f"c{i}", response="x") for i in range(1, 5)]
    )
    call = f"evaluate(dataset, {len(chosen)} metric(s), {kwargs or 'defaults'})"
    try:
        result = evaluate(dataset, chosen, show_progress=False, **kwargs)
    except Exception as exc:
        return {"call": call, "raised": f"{type(exc).__name__}: {exc}"}
    return {
        "call": call,
        "raised": None,
        "repr": repr(result),
        "scores": clean(result.scores),
    }


def run_experiment():
    import pandas as pd
    from ragas import Dataset, experiment
    from ragas.metrics import numeric_metric

    @numeric_metric(name="judge", allowed_values=(0.0, 1.0))
    def judge_raises(case_id: str) -> float:
        if case_id != "c1":
            raise RuntimeError("judge quota exhausted")
        return 1.0

    @numeric_metric(name="judge", allowed_values=(0.0, 1.0))
    def judge_returns_none(case_id: str) -> t.Optional[float]:
        if case_id != "c1":
            return None
        return 1.0

    async def row_from(metric, row):
        result = await metric.ascore(case_id=row["case_id"])
        return {"case_id": row["case_id"], "judge": result.value, "reason": result.reason}

    @experiment()
    async def experiment_metric_raises(row):
        return await row_from(judge_raises, row)

    @experiment()
    async def experiment_metric_returns_none(row):
        return await row_from(judge_returns_none, row)

    @experiment()
    async def experiment_task_raises(row):
        if row["case_id"] != "c1":
            raise RuntimeError("model timeout")
        return {"case_id": row["case_id"], "judge": 1.0, "reason": None}

    @experiment()
    async def experiment_task_returns_none(row):
        if row["case_id"] != "c1":
            return None
        return {"case_id": row["case_id"], "judge": 1.0, "reason": None}

    func = locals()[SCENARIO]
    dataset = Dataset(name="cases", backend="local/csv", root_dir=str(ROOT))
    for i in range(1, 5):
        dataset.append({"case_id": f"c{i}"})
    dataset.save()
    try:
        asyncio.run(func.arun(dataset, name=SCENARIO))
    except Exception as exc:
        return {"raised": f"{type(exc).__name__}: {exc}"}
    saved = ROOT / "experiments" / f"{SCENARIO}.csv"
    frame = pd.read_csv(saved)
    return {
        "raised": None,
        "dataset_rows": len(dataset),
        "saved_csv": saved.read_text().splitlines(),
        "saved_rows": len(frame),
        "pandas_judge_mean": clean(float(frame["judge"].mean())),
        "pandas_judge_count": int(frame["judge"].count()),
    }


result = run_evaluate() if SCENARIO.startswith("evaluate_") else run_experiment()
OUT.write_text(json.dumps(result))
"""

SCENARIOS = [
    "evaluate_metric_raises",
    "evaluate_metric_raises_raise_exceptions",
    "evaluate_metric_returns_none",
    "evaluate_metric_returns_nan",
    "evaluate_two_metrics_same_name",
    "experiment_metric_raises",
    "experiment_metric_returns_none",
    "experiment_task_raises",
    "experiment_task_returns_none",
]


def run(workdir: Path, scenario: str) -> dict[str, Any]:
    out = workdir / f"{scenario}.json"
    root = workdir / scenario
    root.mkdir()
    proc = subprocess.run(
        [sys.executable, "-I", str(workdir / "probe_child.py"), scenario, str(out), str(root)],
        cwd=workdir,
        env={**os.environ, "RAGAS_DO_NOT_TRACK": "true", "NO_COLOR": "1"},
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0 or not out.exists():
        raise SystemExit(f"{scenario}: probe failed\n{proc.stdout}\n{proc.stderr}")
    result: dict[str, Any] = json.loads(out.read_text())
    # What a user sees instead of a recorded error: ragas' executor logs one line per failed job;
    # `@experiment` prints one warning per failed row.
    result["logged_job_errors"] = proc.stderr.count("Exception raised in Job[")
    result["printed_task_warnings"] = proc.stdout.count("Warning: Task failed with error:")
    return result


def main() -> None:
    installed = version("ragas")
    if installed != VERSION:
        raise SystemExit(f"expected ragas {VERSION}, found {installed}")
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "probe_child.py").write_text(CHILD)
        scenarios = {name: run(workdir, name) for name in SCENARIOS}
    report = {
        "framework": "ragas",
        "version": VERSION,
        "generated_by": "scripts/research/ragas_probe.py",
        "scenarios": scenarios,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}")


if __name__ == "__main__":
    main()
