"""examples/github-action.yml: its eval-preflight steps gate as documented."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "pydantic_evals"


def run_example(results: Path, workdir: Path) -> subprocess.CompletedProcess[str]:
    script = ROOT / "scripts" / "run_action_example.py"
    return subprocess.run(
        [sys.executable, str(script), "--results", str(results), "--workdir", str(workdir)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("fixture", "code", "verdict"),
    [("clean_run.json", 0, "PASS"), ("partial_coverage.json", 1, "FAIL")],
)
def test_example_gates_on_the_verdict(
    tmp_path: Path, fixture: str, code: int, verdict: str
) -> None:
    proc = run_example(FIXTURES / fixture, tmp_path)
    assert proc.returncode == code, proc.stderr
    assert f"Verdict: {verdict}" in proc.stdout
    # The report artifact is written whatever the verdict.
    assert json.loads((tmp_path / "preflight.json").read_text())["verdict"] == verdict
