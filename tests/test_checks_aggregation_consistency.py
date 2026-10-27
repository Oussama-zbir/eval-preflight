from typing import Any

import pytest

from eval_preflight import CheckConfig, EvalRun, Finding, check
from tests.builders import case, m, run


def findings(result_run: EvalRun, **config: Any) -> list[Finding]:
    return check(result_run, CheckConfig(**config)).by_check("aggregation-consistency")


def by_subject(found: list[Finding]) -> dict[str, Finding]:
    """Estimator findings, keyed by evaluator id or group."""
    return {
        f.details["evaluator_id"] or f.details["group"]: f
        for f in found
        if "reported_key" not in f.details
    }


def reported_finding(found: list[Finding]) -> Finding:
    (finding,) = [f for f in found if "reported_key" in f.details]
    return finding


def reported(result_run: EvalRun, **aggregates: float) -> EvalRun:
    return result_run.model_copy(update={"reported_aggregates": aggregates})


def repeat_divergence() -> EvalRun:
    """SPEC §9 scenario C: 2 cases, repeat=2; a has one passing assertion, b three failing."""
    cases = []
    for i in (0, 1):
        cases.append(case("a", m("A()", True, kind="assertion"), run_index=i))
        failing = [m(f"B{n}()", False, kind="assertion") for n in (1, 2, 3)]
        cases.append(case("b", *failing, run_index=i))
    return run(*cases)


def test_single_run_estimators_agree() -> None:
    result = by_subject(findings(run(case("c1", m("e", 0.2)), case("c2", m("e", 0.8)))))
    assert result["e"].severity == "PASS"
    assert result["e"].message == "e: pooled = mean of per-case means = 0.5"
    assert result["e"].details["values"] == 2
    assert result["e"].details["cases"] == 2


def test_scenario_c_assertion_group_warns_with_both_values() -> None:
    found = findings(repeat_divergence())
    group = by_subject(found)["assertions"]
    assert group.severity == "WARN"
    assert group.message == "all assertions: pooled mean 0.25 vs mean of per-case means 0.5"
    assert group.details["pooled"] == 0.25
    assert group.details["mean_of_cases"] == 0.5
    # Each assertion appears on one case only, so per-evaluator averages agree.
    assert [f.severity for f in found if f.details["evaluator_id"]] == ["PASS"] * 4


def test_scenario_c_reported_number_is_attributed_to_mean_of_cases() -> None:
    finding = reported_finding(findings(reported(repeat_divergence(), assertions=0.5)))
    assert finding.severity == "PASS"
    assert finding.details["reproduced_by"] == "mean_of_cases"
    assert finding.message == (
        'reported "assertions" = 0.5 reproduced as the mean of per-case means '
        "from 2 of 2 cases (pooled mean: 0.25)"
    )


def test_reported_pooled_mean_is_attributed_to_pooled() -> None:
    found = findings(reported(repeat_divergence(), assertions=0.25))
    finding = reported_finding(found)
    assert finding.severity == "PASS"
    assert finding.details["reproduced_by"] == "pooled"
    assert "reproduced as the pooled mean from 2 of 2 cases" in finding.message


def test_strict_aggregation_turns_divergence_into_fail() -> None:
    group = by_subject(findings(repeat_divergence(), strict_aggregation=True))["assertions"]
    assert group.severity == "FAIL"


def test_uneven_repeat_coverage_diverges_per_evaluator() -> None:
    result_run = run(
        case("a", m("e", 1.0), run_index=0),
        case("a", m("e", 1.0), run_index=1),
        case("b", m("e", 0.0), run_index=0),
        case("b", m("e", None, error="boom"), run_index=1),
    )
    finding = by_subject(findings(result_run))["e"]
    assert finding.severity == "WARN"
    assert finding.details["pooled"] == pytest.approx(2 / 3)
    assert finding.details["mean_of_cases"] == 0.5


def test_difference_within_tolerance_passes_and_just_outside_warns() -> None:
    result_run = run(
        case("a", m("e", 1.0), run_index=0),
        case("a", m("e", 1.0), run_index=1),
        case("b", m("e", 0.0), run_index=0),
        case("b", m("e", None), run_index=1),
    )
    # pooled 2/3 vs 0.5 differ by 1/6.
    assert by_subject(findings(result_run, aggregation_tolerance=0.17))["e"].severity == "PASS"
    assert by_subject(findings(result_run, aggregation_tolerance=0.16))["e"].severity == "WARN"


def test_reported_aggregate_from_partial_coverage_states_the_case_count() -> None:
    # SPEC §9 scenario A: the reported 1.0 is reproducible, but only from 1 of 4 cases.
    result_run = run(
        case("c1", m("FlakyScore()", 1.0, display="FlakyScore")),
        *(
            case(c, m("FlakyScore()", None, display="FlakyScore", error="RuntimeError: x"))
            for c in ("c2", "c3", "c4")
        ),
    )
    found = findings(reported(result_run, FlakyScore=1.0))
    finding = reported_finding(found)
    assert finding.severity == "PASS"
    assert finding.message == 'reported "FlakyScore" = 1 reproduced from 1 of 4 cases'
    assert finding.details["reproduced_by"] == "both"
    assert finding.details["cases_with_values"] == 1
    assert finding.details["eligible_cases"] == 4


def test_reported_aggregate_matching_neither_estimator_fails() -> None:
    result_run = reported(run(case("c1", m("e", 0.2)), case("c2", m("e", 0.8))), e=0.9)
    finding = reported_finding(findings(result_run))
    assert finding.severity == "FAIL"
    assert finding.message == (
        'reported "e" = 0.9 matches neither pooled mean 0.5 nor mean of per-case means 0.5'
    )
    assert finding.details["reproduced_by"] is None


def test_reported_aggregate_is_keyed_by_display_name() -> None:
    # Two ids under one display name: the framework averaged them together, and so do we.
    result_run = run(
        case("c1", m("Judge(strict)", 0.0, display="Judge")),
        case("c2", m("Judge(lenient)", 1.0, display="Judge")),
    )
    finding = reported_finding(findings(reported(result_run, Judge=0.5)))
    assert finding.severity == "PASS"


def test_reported_aggregate_without_raw_values_warns() -> None:
    result_run = reported(run(case("c1", m("e", 0.2))), latency=1.3)
    finding = reported_finding(findings(result_run))
    assert finding.severity == "WARN"
    assert finding.message == (
        'reported "latency" = 1.3 cannot be checked: no numeric values filed under that name'
    )


def test_labels_and_failed_tasks_are_not_averaged() -> None:
    result_run = run(
        case("c1", m("tone", "polite", kind="label"), m("e", 1.0)),
        case("c2", m("e", 0.0), task_error="boom"),
    )
    result = by_subject(findings(result_run))
    assert set(result) == {"e"}
    assert result["e"].details["values"] == 1


def test_no_values_produces_no_findings() -> None:
    assert findings(run(case("c1", m("e", None, error="x")))) == []


def test_booleans_average_as_zero_and_one() -> None:
    result_run = run(
        case("c1", m("ok", True, kind="assertion")), case("c2", m("ok", False, kind="assertion"))
    )
    assert by_subject(findings(result_run))["ok"].details["pooled"] == 0.5
