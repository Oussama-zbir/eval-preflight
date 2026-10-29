import math
from typing import Any

from eval_preflight import CheckConfig, EvalRun, Finding, check
from tests.builders import case, m, run


def findings(candidate: EvalRun, baseline: EvalRun, **config: Any) -> list[Finding]:
    result = check(candidate, CheckConfig(**config), baseline=baseline)
    return result.by_check("baseline-comparability")


def by_kind(found: list[Finding]) -> dict[str, Finding]:
    """Keyed by details.kind; coverage findings as "coverage:<evaluator id>"."""
    return {
        f"coverage:{f.details['evaluator_id']}"
        if f.details.get("kind") == "coverage"
        # The single PASS finding has no kind.
        else f.details.get("kind", "pass"): f
        for f in found
    }


def four_cases(*skip: str, error_on: str | None = None) -> EvalRun:
    cases = []
    for c in ("c1", "c2", "c3", "c4"):
        if c in skip:
            continue
        e = m("e", None, error="x") if c == error_on else m("e", 0.5)
        cases.append(case(c, e, m("f", True, kind="assertion")))
    return run(*cases)


def test_without_baseline_the_check_does_not_run() -> None:
    assert check(four_cases()).by_check("baseline-comparability") == []


def test_identical_runs_pass() -> None:
    [finding] = findings(four_cases(), four_cases())
    assert finding.severity == "PASS"
    assert finding.message == "same cases, evaluators and repeats as the baseline; no coverage drop"


def test_removed_case_warns() -> None:
    found = by_kind(findings(four_cases("c4"), four_cases()))
    assert set(found) == {"cases"}
    assert found["cases"].severity == "WARN"
    assert found["cases"].message == "cases differ from the baseline: removed c4"
    assert found["cases"].details == {
        "kind": "cases",
        "added": [],
        "removed": ["c4"],
    }


def test_added_and_removed_cases_are_both_listed() -> None:
    candidate = run(
        *four_cases("c4").cases, case("c5", m("e", 0.5), m("f", True, kind="assertion"))
    )
    found = by_kind(findings(candidate, four_cases()))
    assert found["cases"].message == "cases differ from the baseline: added c5; removed c4"


def test_require_same_cases_turns_case_differences_into_fail() -> None:
    found = by_kind(findings(four_cases("c4"), four_cases(), require_same_cases=True))
    assert found["cases"].severity == "FAIL"


def test_evaluator_set_difference_warns_or_fails_with_require_same_cases() -> None:
    baseline = four_cases()
    candidate = run(*[case(c.case_id, m("e", 0.5), m("g", 1.0)) for c in baseline.cases])
    found = by_kind(findings(candidate, baseline))
    assert found["evaluators"].severity == "WARN"
    assert found["evaluators"].message == "evaluators differ from the baseline: added g; removed f"
    assert by_kind(findings(candidate, baseline, require_same_cases=True))[
        "evaluators"
    ].severity == ("FAIL")


def test_coverage_drop_fails_with_both_fractions() -> None:
    found = by_kind(findings(four_cases("c4", error_on="c2"), four_cases()))
    drop = found["coverage:e"]
    assert drop.severity == "FAIL"
    assert drop.message == "e coverage dropped from 4/4 (100%) in the baseline to 2/3 (66.6%)"
    assert drop.details == {
        "kind": "coverage",
        "evaluator_id": "e",
        "baseline_covered": 4,
        "baseline_eligible": 4,
        "covered": 2,
        "eligible": 3,
    }
    assert "coverage:f" not in found


def test_equal_coverage_rate_is_not_a_drop() -> None:
    # 3/4 and 6/8 are the same rate; compared as exact fractions, not floats.
    baseline = run(*[case(f"c{i}", m("e", 0.5 if i % 4 else None)) for i in range(8)])
    candidate = run(*[case(f"c{i}", m("e", 0.5 if i % 4 else None)) for i in range(4)])
    found = by_kind(findings(candidate, baseline, min_coverage=0.0))
    assert "coverage:e" not in found


def test_coverage_improvement_is_not_flagged() -> None:
    found = by_kind(findings(four_cases(), four_cases(error_on="c2")))
    assert [f.severity for f in found.values()] == ["PASS"]


def test_non_finite_values_do_not_count_as_coverage_in_either_run() -> None:
    baseline = run(*[case(f"c{i}", m("e", 0.5)) for i in range(4)])
    candidate = run(*[case(f"c{i}", m("e", math.nan if i == 0 else 0.5)) for i in range(4)])
    assert by_kind(findings(candidate, baseline))["coverage:e"].severity == "FAIL"


def test_candidate_with_no_eligible_case_runs_drops_to_zero() -> None:
    baseline = run(case("c1", m("e", 0.5)))
    candidate = run(case("c1", m("e", None, error="x"), task_error="boom"))
    drop = by_kind(findings(candidate, baseline, max_task_failure_rate=1.0))["coverage:e"]
    assert drop.message == "e coverage dropped from 1/1 (100%) in the baseline to 0/0"


def test_repeat_count_mismatch_warns() -> None:
    baseline = run(case("a", m("e", 1.0)), case("b", m("e", 0.0)))
    candidate = run(
        *[case(c, m("e", v), run_index=i) for c, v in (("a", 1.0), ("b", 0.0)) for i in (0, 1)]
    )
    found = by_kind(findings(candidate, baseline))
    assert set(found) == {"repeats"}
    assert found["repeats"].severity == "WARN"
    assert found["repeats"].message == "repeat counts differ from the baseline: a 1 → 2, b 1 → 2"
    assert found["repeats"].details["counts"] == {"a": [1, 2], "b": [1, 2]}


def test_repeat_counts_include_failed_case_runs() -> None:
    baseline = run(case("a", m("e", 1.0), run_index=0), case("a", m("e", 1.0), run_index=1))
    candidate = run(case("a", m("e", 1.0), run_index=0), case("a", task_error="x", run_index=1))
    found = by_kind(findings(candidate, baseline, max_task_failure_rate=1.0, min_coverage=0.0))
    assert "repeats" not in found
