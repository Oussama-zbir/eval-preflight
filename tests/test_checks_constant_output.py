import math
from typing import Any

import pytest

from eval_preflight import CheckConfig, EvalRun, Finding, check
from tests.builders import case, m, run


def findings(result_run: EvalRun, **config: Any) -> list[Finding]:
    return check(result_run, CheckConfig(**config)).by_check("constant-output")


def constant_run(n: int, value: float | str = 1.0, **kw: Any) -> EvalRun:
    return run(*[case(f"c{i}", m("j", value, **kw)) for i in range(n)])


def test_constant_score_over_min_case_runs_warns() -> None:
    [finding] = findings(constant_run(5))
    assert finding.severity == "WARN"
    assert finding.message == "j returned 1.0 on all 5 case-runs"
    assert finding.details == {
        "evaluator_id": "j",
        "value": "1.0",
        "case_runs_with_value": 5,
        "eligible": 5,
        "min_cases": 5,
    }


def test_constant_label_warns() -> None:
    [finding] = findings(constant_run(6, "positive", kind="label"))
    assert finding.severity == "WARN"
    assert finding.message == "j returned 'positive' on all 6 case-runs"


def test_below_min_case_runs_passes() -> None:
    [finding] = findings(constant_run(4))
    assert finding.severity == "PASS"
    assert finding.details["min_cases"] == 5


def test_min_cases_for_constant_is_configurable() -> None:
    assert [f.severity for f in findings(constant_run(4), min_cases_for_constant=4)] == ["WARN"]
    assert [f.severity for f in findings(constant_run(5), min_cases_for_constant=6)] == ["PASS"]


def test_varying_values_pass() -> None:
    result_run = run(*[case(f"c{i}", m("j", 1.0)) for i in range(5)], case("c5", m("j", 0.9)))
    [finding] = findings(result_run)
    assert finding.severity == "PASS"
    assert finding.message == "no score or label evaluator returned a single value on ≥5 case-runs"


def test_assertions_are_exempt() -> None:
    # An assertion that passes everywhere is the goal, not a stuck judge (SPEC §15).
    [finding] = findings(constant_run(10, True, kind="assertion"))
    assert finding.severity == "PASS"


def test_gaps_do_not_disable_the_check() -> None:
    result_run = run(
        *[case(f"c{i}", m("j", 1.0)) for i in range(5)],
        case("c5", m("j", None, error="RuntimeError: x")),
        case("c6"),
    )
    [finding] = findings(result_run, min_coverage=0.0, max_evaluator_error_rate=1.0)
    assert finding.severity == "WARN"
    assert finding.message == "j returned 1.0 on all 5 case-runs with a value (of 7 eligible)"


def test_non_finite_and_failed_task_case_runs_are_not_counted() -> None:
    result_run = run(
        *[case(f"c{i}", m("j", 0.5)) for i in range(4)],
        case("c4", m("j", math.nan)),
        case("c5", m("j", 0.9), task_error="boom"),
    )
    [finding] = findings(result_run)
    assert finding.severity == "PASS"


def test_int_like_values_compare_numerically() -> None:
    result_run = run(*[case(f"c{i}", m("j", 1.0)) for i in range(4)], case("c4", m("j", 1)))
    assert [f.severity for f in findings(result_run)] == ["WARN"]


def test_one_finding_per_constant_evaluator() -> None:
    result_run = run(
        *[case(f"c{i}", m("a", 0.0), m("b", "x", kind="label"), m("c", i / 10)) for i in range(5)]
    )
    found = findings(result_run)
    assert [(f.details["evaluator_id"], f.severity) for f in found] == [
        ("a", "WARN"),
        ("b", "WARN"),
    ]


@pytest.mark.parametrize("bad", [0, 1, -3])
def test_min_cases_below_two_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="min_cases_for_constant"):
        CheckConfig(min_cases_for_constant=bad)
