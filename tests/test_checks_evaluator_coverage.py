import math
from typing import Any

import pytest

from eval_preflight import CheckConfig, EvalRun, Finding, check
from tests.builders import case, m, run


def findings(result_run: EvalRun, **config: Any) -> dict[str, Finding]:
    found = check(result_run, CheckConfig(**config)).by_check("evaluator-coverage")
    return {
        f.details.get("evaluator_id", ""): f for f in found if f.details.get("kind") != "non_finite"
    }


def test_full_coverage_passes_with_n_of_n() -> None:
    result = findings(run(case("c1", m("e", 1.0)), case("c2", m("e", 0.0))))
    assert result["e"].severity == "PASS"
    assert result["e"].message == "e scored 2/2 case-runs (100%)"


def test_missing_value_fails_and_lists_uncovered_case_runs() -> None:
    result = findings(
        run(
            case("c1", m("flaky", 1.0)),
            case("c2", m("flaky", None, error="RuntimeError: x")),
            case("c3"),
            case("c4", m("flaky", None)),
        )
    )
    finding = result["flaky"]
    assert finding.severity == "FAIL"
    assert finding.message == "flaky scored 1/4 case-runs (25%)"
    assert finding.details["covered"] == 1
    assert finding.details["eligible"] == 4
    assert finding.details["uncovered_case_runs"] == ["c2", "c3", "c4"]


def test_one_finding_per_evaluator_id_not_per_display_name() -> None:
    result = findings(
        run(
            case("c1", m("strict", 0.0, display="Judge"), m("lenient", 1.0, display="Judge_2")),
            case("c2", m("lenient", 1.0, display="Judge")),
        )
    )
    assert set(result) == {"strict", "lenient"}
    assert result["strict"].message == "strict scored 1/2 case-runs (50%)"
    assert result["lenient"].severity == "PASS"


def test_task_failures_are_not_eligible() -> None:
    result = findings(run(case("c1", m("e", 1.0)), case("c2", task_error="boom")))
    assert result["e"].severity == "PASS"
    assert result["e"].details["eligible"] == 1


def test_coverage_equal_to_threshold_passes() -> None:
    result = findings(run(case("c1", m("e", 1.0)), case("c2")), min_coverage=0.5)
    assert result["e"].severity == "PASS"


def test_coverage_just_below_threshold_fails() -> None:
    result = findings(run(case("c1", m("e", 1.0)), case("c2")), min_coverage=0.51)
    assert result["e"].severity == "FAIL"


def test_near_complete_coverage_is_not_rounded_up_to_100_percent() -> None:
    cases = [case(f"c{i}", m("e", 1.0)) for i in range(999)] + [case("c999")]
    result = findings(run(*cases))
    assert result["e"].message == "e scored 999/1000 case-runs (99.9%)"


def test_tiny_nonzero_coverage_is_not_rounded_down_to_zero() -> None:
    cases = [case("c0", m("e", 1.0))] + [case(f"c{i}") for i in range(1, 2000)]
    result = findings(run(*cases))
    assert result["e"].message == "e scored 1/2000 case-runs (<0.1%)"


def test_zero_coverage_reads_zero_percent() -> None:
    result = findings(run(case("c1", m("e", None, error="x")), case("c2")))
    assert result["e"].message == "e scored 0/2 case-runs (0%)"


def test_false_and_zero_count_as_coverage() -> None:
    result = findings(run(case("c1", m("a", False, kind="assertion")), case("c2", m("a", 0.0))))
    assert result["a"].severity == "PASS"


def test_evaluator_seen_only_on_failed_tasks_has_no_eligible_case_runs() -> None:
    result = findings(
        run(case("c1", m("e", 1.0, error="x"), task_error="boom")),
        max_task_failure_rate=1.0,
    )
    assert result["e"].severity == "FAIL"
    assert result["e"].message == "e has no eligible case-runs"


def test_run_without_any_evaluator_fails() -> None:
    result = findings(run(case("c1"), case("c2")))
    [finding] = result.values()
    assert finding.severity == "FAIL"
    assert finding.message == "no evaluator produced a measurement on any case-run"


def non_finite(result_run: EvalRun) -> list[Finding]:
    found = check(result_run).by_check("evaluator-coverage")
    return [f for f in found if f.details.get("kind") == "non_finite"]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_value_is_not_coverage_and_fails(bad: float) -> None:
    result_run = run(case("c1", m("e", 1.0)), case("c2", m("e", bad)))
    assert findings(result_run)["e"].message == "e scored 1/2 case-runs (50%)"
    assert findings(result_run)["e"].details["uncovered_case_runs"] == ["c2"]
    [finding] = non_finite(result_run)
    assert finding.severity == "FAIL"
    assert finding.message == f"e returned a non-finite value on 1/2 case-runs: {bad!r}"
    assert finding.details["non_finite_case_runs"] == ["c2"]
    # Strings, so a JSON report of the details stays valid JSON.
    assert finding.details["values"] == [repr(bad)]


def test_non_finite_fails_even_when_coverage_threshold_tolerates_the_gap() -> None:
    result_run = run(*[case(f"c{i}", m("e", 0.5)) for i in range(9)], case("c9", m("e", math.nan)))
    result = check(result_run, CheckConfig(min_coverage=0.9))
    coverage = [f for f in result.by_check("evaluator-coverage") if "covered" in f.details]
    assert [f.severity for f in coverage] == ["PASS"]
    assert [f.severity for f in non_finite(result_run)] == ["FAIL"]
    assert result.verdict == "FAIL"


def test_finite_values_produce_no_non_finite_finding() -> None:
    result_run = run(case("c1", m("e", 1e308)), case("c2", m("e", -0.0)), case("c3", m("b", True)))
    assert non_finite(result_run) == []


def test_non_finite_on_failed_task_is_ignored() -> None:
    result_run = run(case("c1", m("e", 1.0)), case("c2", m("e", math.nan), task_error="boom"))
    found = check(result_run, CheckConfig(max_task_failure_rate=1.0)).by_check("evaluator-coverage")
    assert [f.details.get("kind") for f in found] == [None]


def test_case_run_with_a_finite_and_a_non_finite_value_is_covered_but_flagged() -> None:
    result_run = run(case("c1", m("e", 1.0), m("e", math.inf)))
    assert findings(result_run)["e"].severity == "PASS"
    assert [f.severity for f in non_finite(result_run)] == ["FAIL"]
