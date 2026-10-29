import io
import json
import math

import pytest
from rich.console import Console

from eval_preflight import CheckResult, Finding, IntegrityError, render
from tests.builders import case, m, run


def result_with(*severities: str) -> CheckResult:
    findings = [
        Finding(check=f"check-{i}", severity=s, message=f"message {i}")  # type: ignore[arg-type]
        for i, s in enumerate(severities)
    ]
    return CheckResult(run=run(case("c1")), findings=findings)


@pytest.mark.parametrize(
    ("severities", "verdict"),
    [
        ((), "PASS"),
        (("PASS", "PASS"), "PASS"),
        (("PASS", "WARN"), "WARN"),
        (("WARN", "FAIL", "PASS"), "FAIL"),
    ],
)
def test_verdict(severities: tuple[str, ...], verdict: str) -> None:
    assert result_with(*severities).verdict == verdict


@pytest.mark.parametrize(
    ("severities", "warnings_as_errors", "code"),
    [
        (("PASS",), False, 0),
        (("PASS",), True, 0),
        (("WARN",), False, 0),
        (("WARN",), True, 1),
        (("FAIL",), False, 1),
    ],
)
def test_exit_code(severities: tuple[str, ...], warnings_as_errors: bool, code: int) -> None:
    assert result_with(*severities).exit_code(warnings_as_errors=warnings_as_errors) == code


def test_raise_if_failed_carries_only_fail_findings() -> None:
    with pytest.raises(IntegrityError, match="message 1") as exc:
        result_with("WARN", "FAIL", "PASS").raise_if_failed()
    assert [f.check for f in exc.value.findings] == ["check-1"]


def test_raise_if_failed_is_silent_on_warnings() -> None:
    result_with("WARN").raise_if_failed()


def test_render_counts_warnings_and_failures() -> None:
    buffer = io.StringIO()
    render(result_with("WARN", "FAIL", "WARN"), Console(file=buffer, width=200))
    lines = buffer.getvalue().splitlines()
    assert lines[2] == "WARN  check-0                 message 0"
    assert lines[-1] == "Verdict: FAIL (1 failure, 2 warnings)"


def test_render_escapes_rich_markup_in_messages() -> None:
    buffer = io.StringIO()
    result = CheckResult(
        run=run(case("c1")),
        findings=[Finding(check="x", severity="PASS", message="[bold]Judge[/bold]")],
    )
    render(result, Console(file=buffer, width=200))
    assert "[bold]Judge[/bold]" in buffer.getvalue()


def test_to_json_has_verdict_run_and_findings() -> None:
    result = CheckResult(
        run=run(case("a", run_index=0), case("a", run_index=1), case("b", m("e", 1.0))),
        findings=[Finding(check="x", severity="WARN", message="m", details={"k": [1, "v"]})],
    )
    document = json.loads(result.to_json())
    assert document == {
        "verdict": "WARN",
        "run": {
            "name": "test",
            "source": "generic",
            "source_version": None,
            "cases": 2,
            "case_runs": 3,
            "evaluators": ["e"],
            "baseline": None,
        },
        "findings": [
            {"check": "x", "severity": "WARN", "message": "m", "details": {"k": [1, "v"]}}
        ],
    }


def test_to_json_is_valid_json_even_with_non_finite_details() -> None:
    # Checks store non-finite values as strings; anything else becomes null, never NaN.
    result = CheckResult(
        run=run(case("c1")),
        findings=[Finding(check="x", severity="PASS", message="m", details={"v": math.inf})],
    )
    text = result.to_json()
    assert "Infinity" not in text
    assert json.loads(text)["findings"][0]["details"] == {"v": None}
