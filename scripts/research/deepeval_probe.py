# /// script
# requires-python = ">=3.11"
# dependencies = ["deepeval==4.3.4", "pytest==9.2.0"]
# ///
"""Probe how deepeval reports partial and failed scoring (docs/research-notes.md).

Run with `make research` (equivalently
`uv run --no-project scripts/research/deepeval_probe.py`). No API key and no network: every
metric is deterministic (a custom `BaseMetric`, or deepeval's built-in `ExactMatchMetric`), and
telemetry is switched off with `DEEPEVAL_TELEMETRY_OPT_OUT`.

Four test cases `c1`..`c4`, each checked with `assert_test` in one parametrized pytest test. Each
scenario differs only in its metrics or in a `deepeval test run` flag:

- `metric_raises`: a custom metric raises on c2-c4.
- `metric_raises_ignore_errors`: same, with `--ignore-errors`.
- `metric_sets_no_score`: a custom metric returns on c2-c4 without setting `score` or `success`.
- `missing_params`: `ExactMatchMetric`, with `expected_output` set only on c1.
- `missing_params_skip`: same, with `--skip-on-missing-params`.
- `two_metrics_same_name`: two custom metrics both named `judge`; `strict` scores 0.0 on c1 and
  sets no score elsewhere, `lenient` scores 1.0 everywhere.

Each scenario runs `deepeval test run`, whose exit code is what a CI step sees, and reads back
the test run deepeval saves to `.deepeval/.latest_test_run.json`. `evaluate_metric_raises` calls
`deepeval.evaluate()` with the `metric_raises` metric instead and records whether it raises.
Writes docs/research/deepeval-<version>.json. Never hand-edit the output; change this script and
rerun.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any

VERSION = "4.3.4"
OUT = Path(__file__).resolve().parents[2] / "docs" / "research" / f"deepeval-{VERSION}.json"

METRICS = """\
from deepeval.metrics import BaseMetric


class Judge(BaseMetric):
    # Scores c1 only; on c2-c4 `mode` decides what happens instead.
    def __init__(self, mode, threshold=0.5):
        self.mode = mode
        self.threshold = threshold

    @property
    def __name__(self):
        return "judge"

    def measure(self, test_case, *args, **kwargs):
        if test_case.input != "c1":
            if self.mode == "raise":
                raise RuntimeError("judge quota exhausted")
            if self.mode in ("no_score", "strict"):
                return None
        self.score = 0.0 if self.mode == "strict" else 1.0
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case, *args, **kwargs):
        return self.measure(test_case)

    def is_successful(self):
        return self.success
"""

TEST_FILE = """\
import os

import pytest
from deepeval import assert_test
from deepeval.metrics import ExactMatchMetric
from deepeval.test_case import LLMTestCase

from probe_metrics import Judge

SCENARIO = os.environ["PROBE_SCENARIO"]


@pytest.mark.parametrize("case_id", ["c1", "c2", "c3", "c4"])
def test_case(case_id):
    if SCENARIO == "missing_params":
        expected = "x" if case_id == "c1" else None
        test_case = LLMTestCase(input=case_id, actual_output="x", expected_output=expected)
        assert_test(test_case, [ExactMatchMetric()])
        return
    test_case = LLMTestCase(input=case_id, actual_output="x")
    if SCENARIO == "same_name":
        assert_test(test_case, [Judge("strict"), Judge("lenient")])
    else:
        assert_test(test_case, [Judge(SCENARIO)])
"""

EVALUATE_FILE = """\
from deepeval import evaluate
from deepeval.evaluate.configs import DisplayConfig
from deepeval.test_case import LLMTestCase

from probe_metrics import Judge

cases = [LLMTestCase(input=f"c{i}", actual_output="x") for i in range(1, 5)]
display = DisplayConfig(print_results=False, show_indicator=False, inspect_after_run=False)
try:
    evaluate(cases, [Judge("raise")], display_config=display)
except Exception as exc:
    print(f"raised {type(exc).__name__}: {exc}")
else:
    print("returned")
"""

# (name, metric mode in TEST_FILE, `deepeval test run` flags)
SCENARIOS: list[tuple[str, str, list[str]]] = [
    ("metric_raises", "raise", []),
    ("metric_raises_ignore_errors", "raise", ["--ignore-errors"]),
    ("metric_sets_no_score", "no_score", []),
    ("missing_params", "missing_params", []),
    ("missing_params_skip", "missing_params", ["--skip-on-missing-params"]),
    ("two_metrics_same_name", "same_name", []),
]

ANSI = re.compile(r"\x1b\[[0-9;]*m")
PYTEST_COUNT = re.compile(r"(\d+) (passed|failed|error|errors)\b")


def _env(scenario: str) -> dict[str, str]:
    return {
        **os.environ,
        "PROBE_SCENARIO": scenario,
        "DEEPEVAL_TELEMETRY_OPT_OUT": "1",
        "DEEPEVAL_NO_INSPECT_PROMPT": "1",
        "NO_COLOR": "1",
    }


def _pytest_summary(stdout: str) -> dict[str, int]:
    # The last line with counts is pytest's own summary, e.g. "3 failed, 1 passed, 4 warnings".
    lines = [line for line in ANSI.sub("", stdout).splitlines() if PYTEST_COUNT.search(line)]
    return {kind: int(n) for n, kind in PYTEST_COUNT.findall(lines[-1])} if lines else {}


def run(workdir: Path, scenario: str, flags: list[str]) -> dict[str, Any]:
    saved = workdir / ".deepeval" / ".latest_test_run.json"
    saved.unlink(missing_ok=True)
    # The `deepeval` console script installed next to this interpreter (no `python -m deepeval`).
    command = [str(Path(sys.executable).with_name("deepeval")), "test", "run", "test_probe.py"]
    proc = subprocess.run(
        [*command, *flags],
        cwd=workdir,
        env=_env(scenario),
        check=False,
        capture_output=True,
        text=True,
    )
    if not saved.exists():
        raise SystemExit(f"{scenario}: no saved test run\n{proc.stdout}\n{proc.stderr}")
    run_data = json.loads(saved.read_text())["testRunData"]
    return {
        "command": ["deepeval", "test", "run", "test_probe.py", *flags],
        "exit_code": proc.returncode,
        "pytest": _pytest_summary(proc.stdout),
        "saved_test_run": {
            "testPassed": run_data["testPassed"],
            "testFailed": run_data["testFailed"],
            "metricsScores": run_data["metricsScores"],
            "testCases": {
                case["input"]: {
                    "success": case["success"],
                    "metricsData": [
                        {k: metric.get(k) for k in ("name", "score", "success", "error")}
                        for metric in case.get("metricsData") or []
                    ],
                }
                for case in sorted(run_data["testCases"], key=lambda case: case["input"])
            },
        },
    }


def run_evaluate(workdir: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "evaluate_probe.py"],
        cwd=workdir,
        env=_env("evaluate"),
        check=False,
        capture_output=True,
        text=True,
    )
    (outcome,) = [line for line in proc.stdout.splitlines() if line.startswith(("raised", "ret"))]
    return {"call": "deepeval.evaluate(cases, [Judge('raise')])", "outcome": outcome}


def main() -> None:
    installed = version("deepeval")
    if installed != VERSION:
        raise SystemExit(f"expected deepeval {VERSION}, found {installed}")
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "probe_metrics.py").write_text(METRICS)
        (workdir / "test_probe.py").write_text(TEST_FILE)
        (workdir / "evaluate_probe.py").write_text(EVALUATE_FILE)
        scenarios = {name: run(workdir, mode, flags) for name, mode, flags in SCENARIOS}
        scenarios["evaluate_metric_raises"] = run_evaluate(workdir)
    report = {
        "framework": "deepeval",
        "version": VERSION,
        "generated_by": "scripts/research/deepeval_probe.py",
        "scenarios": scenarios,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}")


if __name__ == "__main__":
    main()
