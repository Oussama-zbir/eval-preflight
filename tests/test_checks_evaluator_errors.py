from eval_preflight import CheckConfig, EvalRun, Finding, check
from tests.builders import case, m, run


def findings(result_run: EvalRun, **config: float) -> dict[str, Finding]:
    found = check(result_run, CheckConfig(**config)).by_check("evaluator-errors")
    return {f.details["evaluator_id"]: f for f in found}


def test_no_errors_passes() -> None:
    result = findings(run(case("c1", m("e", 1.0)), case("c2", m("e", 0.0))))
    assert result["e"].severity == "PASS"
    assert result["e"].message == "e errored on 0/2"


def test_errors_fail_with_most_common_message() -> None:
    result = findings(
        run(
            case("c1", m("j", 1.0)),
            case("c2", m("j", None, error="RuntimeError: judge quota exhausted")),
            case("c3", m("j", None, error="RuntimeError: judge quota exhausted")),
            case("c4", m("j", None, error="ValueError: bad json")),
        )
    )
    finding = result["j"]
    assert finding.severity == "FAIL"
    assert finding.message == "j errored on 3/4: RuntimeError: judge quota exhausted"
    assert finding.details["errored"] == 3
    assert finding.details["most_common_error"] == "RuntimeError: judge quota exhausted"
    assert finding.details["error_counts"] == {
        "RuntimeError: judge quota exhausted": 2,
        "ValueError: bad json": 1,
    }
    assert finding.details["errored_case_runs"] == ["c2", "c3", "c4"]


def test_most_common_error_ties_break_on_first_seen() -> None:
    result = findings(run(case("c1", m("j", None, error="B")), case("c2", m("j", None, error="A"))))
    assert result["j"].details["most_common_error"] == "B"


def test_errored_task_case_runs_are_not_counted() -> None:
    result = findings(
        run(case("c1", m("e", 1.0)), case("c2", m("e", None, error="x"), task_error="boom"))
    )
    assert result["e"].message == "e errored on 0/1"


def test_error_rate_equal_to_threshold_passes() -> None:
    result = findings(
        run(case("c1", m("e", 1.0)), case("c2", m("e", None, error="x"))),
        max_evaluator_error_rate=0.5,
    )
    assert result["e"].severity == "PASS"


def test_error_rate_just_above_threshold_fails() -> None:
    result = findings(
        run(case("c1", m("e", 1.0)), case("c2", m("e", None, error="x"))),
        max_evaluator_error_rate=0.49,
    )
    assert result["e"].severity == "FAIL"


def test_one_case_run_with_two_errors_counts_once() -> None:
    result = findings(
        run(
            case("c1", m("e", None, error="x"), m("e", None, error="y")),
            case("c2", m("e", 1.0)),
        )
    )
    assert result["e"].message == "e errored on 1/2: x"
