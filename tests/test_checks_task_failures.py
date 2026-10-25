from eval_preflight import CheckConfig, EvalRun, Finding, check
from tests.builders import case, m, run


def findings(result_run: EvalRun, **config: float) -> list[Finding]:
    return check(result_run, CheckConfig(**config)).by_check("task-failures")


def test_no_task_failures_passes_and_reports_n_of_n() -> None:
    [finding] = findings(run(case("c1", m("e", 1.0)), case("c2", m("e", 0.0))))
    assert finding.severity == "PASS"
    assert finding.message == "0/2"
    assert finding.details["failed"] == 0
    assert finding.details["total"] == 2


def test_any_task_failure_fails_by_default() -> None:
    [finding] = findings(
        run(
            case("c1", m("e", 1.0)),
            case("c2", task_error="TimeoutError: model took too long"),
            case("c3", m("e", 1.0)),
            case("c4", m("e", 1.0)),
        )
    )
    assert finding.severity == "FAIL"
    assert finding.message.startswith("1/4 case-runs (25%) raised")
    assert "TimeoutError: model took too long" in finding.message
    assert finding.details["failed_case_runs"] == ["c2"]


def test_rate_equal_to_threshold_passes() -> None:
    result = run(case("c1", m("e", 1.0)), case("c2", task_error="boom"))
    [finding] = findings(result, max_task_failure_rate=0.5)
    assert finding.severity == "PASS"
    assert finding.message.startswith("1/2")


def test_rate_just_above_threshold_fails() -> None:
    result = run(case("c1", m("e", 1.0)), case("c2", task_error="boom"))
    [finding] = findings(result, max_task_failure_rate=0.49)
    assert finding.severity == "FAIL"


def test_case_run_labels_include_run_index_when_run_has_repeats() -> None:
    result = run(
        case("a", m("e", 1.0), run_index=0),
        case("a", task_error="boom", run_index=1),
    )
    [finding] = findings(result)
    assert finding.details["failed_case_runs"] == ["a[1]"]


def test_empty_run_fails() -> None:
    [finding] = findings(run())
    assert finding.severity == "FAIL"
    assert finding.message == "run contains no case-runs"
