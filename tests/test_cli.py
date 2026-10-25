import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval_preflight.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def row(severity: str, check_id: str, message: str) -> str:
    return f"{severity}  {check_id:<24}{message}"


def run_cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = main(["check", *args])
    out, err = capsys.readouterr()
    return code, out, err


def test_fixture_b_prints_name_collision_mapping_and_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = run_cli(capsys, str(FIXTURES / "name_shift.json"))
    assert code == 1
    mapping = "\"Judge\" → Judge(rubric='strict') on c1; Judge(rubric='lenient') on c2, c3, c4"
    assert row("FAIL", "name-collision", mapping) in out
    assert "Verdict: FAIL" in out


def test_fixture_d_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run_cli(capsys, str(FIXTURES / "clean_run.json"))
    assert code == 0
    assert out.splitlines()[0] == "eval-preflight  clean_run · 4 cases · generic"
    assert "Verdict: PASS" in out
    assert "FAIL " not in out


def test_fixture_a_output(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run_cli(capsys, str(FIXTURES / "partial_coverage.json"))
    assert code == 1
    assert row("FAIL", "evaluator-coverage", "FlakyScore() scored 1/4 case-runs (25%)") in out
    assert row("PASS", "evaluator-coverage", "AlwaysScores() scored 4/4 case-runs (100%)") in out
    assert row("PASS", "task-failures", "0/4") in out
    assert out.rstrip().endswith("Verdict: FAIL (2 failures, 0 warnings)")


def test_header_counts_case_runs_when_repeated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "rep.jsonl"
    rows = [{"case_id": c, "run_index": i} for c in ("a", "b") for i in (0, 1)]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    _, out, _ = run_cli(capsys, str(path), "--min-coverage", "0")
    assert out.splitlines()[0] == "eval-preflight  rep · 2 cases · 4 case-runs · generic"


def test_thresholds_are_passed_through(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, _ = run_cli(
        capsys,
        str(FIXTURES / "partial_coverage.json"),
        "--min-coverage",
        "0.25",
        "--max-evaluator-error-rate",
        "0.75",
    )
    assert code == 0


def test_task_failure_threshold_is_passed_through(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "r.jsonl"
    rows = [
        {
            "case_id": "c1",
            "measurements": [
                {"evaluator_id": "e", "display_name": "e", "kind": "score", "value": 1.0}
            ],
        },
        {"case_id": "c2", "task_error": "boom"},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert run_cli(capsys, str(path))[0] == 1
    assert run_cli(capsys, str(path), "--max-task-failure-rate", "0.5")[0] == 0


def test_quiet_hides_pass_findings(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run_cli(capsys, str(FIXTURES / "partial_coverage.json"), "--quiet")
    assert code == 1
    assert "PASS " not in out
    assert "FAIL  evaluator-coverage" in out
    assert "eval-preflight  " not in out
    assert "Verdict: FAIL" in out


def test_quiet_clean_run_prints_only_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run_cli(capsys, str(FIXTURES / "clean_run.json"), "--quiet")
    assert code == 0
    assert out.strip() == "Verdict: PASS (0 failures, 0 warnings)"


def test_warnings_as_errors_without_warnings_still_passes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, _, _ = run_cli(capsys, str(FIXTURES / "clean_run.json"), "--warnings-as-errors")
    assert code == 0


def test_explicit_generic_format(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, _ = run_cli(capsys, str(FIXTURES / "clean_run.json"), "--format", "generic")
    assert code == 0


def test_missing_file_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run_cli(capsys, str(tmp_path / "nope.json"))
    assert code == 2
    assert out == ""
    assert "cannot read" in err


@pytest.mark.parametrize(
    "args",
    [
        ["--format", "csv"],
        ["--min-coverage", "1.5"],
        ["--max-evaluator-error-rate", "-0.1"],
        ["--max-task-failure-rate", "nan"],
        ["--min-coverage", "abc"],
        ["--no-such-flag"],
    ],
)
def test_bad_flags_exit_2(capsys: pytest.CaptureFixture[str], args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["check", str(FIXTURES / "clean_run.json"), *args])
    assert exc.value.code == 2


def test_missing_command_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_console_script_entry_point() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "eval_preflight", "check", str(FIXTURES / "name_shift.json")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "name-collision" in proc.stdout
