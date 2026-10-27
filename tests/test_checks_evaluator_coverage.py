from typing import Any

from eval_preflight import CheckConfig, EvalRun, Finding, check
from tests.builders import case, m, run


def findings(result_run: EvalRun, **config: Any) -> dict[str, Finding]:
    found = check(result_run, CheckConfig(**config)).by_check("evaluator-coverage")
    return {f.details.get("evaluator_id", ""): f for f in found}


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
