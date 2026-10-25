"""Golden scenarios from SPEC.md §9, run through the Python API.

Milestone 1 uses hand-written generic fixtures for A, B and D. Scenario C needs
aggregation-consistency (Milestone 2) and E needs --baseline (Milestone 3).
"""

from pathlib import Path

from eval_preflight import CheckResult, Finding, check, load

FIXTURES = Path(__file__).parent / "fixtures"


def run_fixture(name: str) -> CheckResult:
    return check(load(FIXTURES / name))


def by_evaluator(findings: list[Finding]) -> dict[str, Finding]:
    return {f.details["evaluator_id"]: f for f in findings}


def test_a_partial_coverage() -> None:
    result = run_fixture("partial_coverage.json")
    coverage = by_evaluator(result.by_check("evaluator-coverage"))
    errors = by_evaluator(result.by_check("evaluator-errors"))

    assert coverage["FlakyScore()"].severity == "FAIL"
    assert coverage["FlakyScore()"].message == "FlakyScore() scored 1/4 case-runs (25%)"
    assert errors["FlakyScore()"].severity == "FAIL"
    assert errors["FlakyScore()"].message == (
        "FlakyScore() errored on 3/4: RuntimeError: judge quota exhausted"
    )
    assert coverage["AlwaysScores()"].severity == "PASS"
    assert coverage["AlwaysScores()"].message == "AlwaysScores() scored 4/4 case-runs (100%)"
    assert errors["AlwaysScores()"].severity == "PASS"
    assert [f.severity for f in result.by_check("task-failures")] == ["PASS"]
    assert [f.severity for f in result.by_check("name-collision")] == ["PASS"]
    assert result.verdict == "FAIL"


def test_b_name_shift() -> None:
    result = run_fixture("name_shift.json")
    strict, lenient = "Judge(rubric='strict')", "Judge(rubric='lenient')"
    collisions = {f.message: f for f in result.by_check("name-collision")}

    assert set(collisions) == {
        f'"Judge" → {strict} on c1; {lenient} on c2, c3, c4',
        f'{lenient} → "Judge_2" on c1; "Judge" on c2, c3, c4',
    }
    assert all(f.severity == "FAIL" for f in collisions.values())

    coverage = by_evaluator(result.by_check("evaluator-coverage"))
    assert coverage[strict].severity == "FAIL"
    assert coverage[strict].message == f"{strict} scored 1/4 case-runs (25%)"
    assert coverage[lenient].severity == "PASS"
    assert by_evaluator(result.by_check("evaluator-errors"))[strict].severity == "FAIL"
    assert result.verdict == "FAIL"


def test_d_clean_run_has_no_false_positives() -> None:
    result = run_fixture("clean_run.json")
    assert result.findings
    assert {f.severity for f in result.findings} == {"PASS"}
    assert result.verdict == "PASS"
    result.raise_if_failed()
