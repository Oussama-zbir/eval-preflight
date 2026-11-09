import pytest
from pydantic import ValidationError

from eval_preflight import CaseResult, EvalRun, Kind, Measurement
from tests.builders import case, m, run


def test_value_types_survive_validation() -> None:
    measurements = [
        Measurement.model_validate(
            {"evaluator": {"id": "e", "display_name": "e", "kind": "score"}, "value": raw}
        )
        for raw in (1, 0.5, True, "yes", None)
    ]
    values = [x.value for x in measurements]
    assert values == [1.0, 0.5, True, "yes", None]
    assert type(values[0]) is float
    assert type(values[2]) is bool


def test_case_result_defaults() -> None:
    result = CaseResult(case_id="c1")
    assert result.run_index == 0
    assert result.task_error is None
    assert result.measurements == []


def test_negative_run_index_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CaseResult(case_id="c1", run_index=-1)


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Measurement.model_validate(
            {"evaluator": {"id": "e", "display_name": "e", "kind": "metric"}, "value": 1.0}
        )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CaseResult.model_validate({"case_id": "c1", "scores": {}})


def test_duplicate_case_run_is_rejected() -> None:
    with pytest.raises(ValidationError, match=r"duplicate case-run \('c1', 0\)"):
        run(case("c1", m("e", 1.0)), case("c1", m("e", 0.0)))


def test_same_case_with_different_run_index_is_allowed() -> None:
    result = run(case("c1", run_index=0), case("c1", run_index=1))
    assert [(c.case_id, c.run_index) for c in result.cases] == [("c1", 0), ("c1", 1)]


def test_eval_run_optional_fields() -> None:
    result = EvalRun(name="r", source="generic", cases=[])
    assert result.source_version is None
    assert result.reported_aggregates is None


def test_duplicate_evaluator_id_in_one_case_run_is_rejected() -> None:
    with pytest.raises(
        ValidationError, match=r"duplicate evaluator id 'e' in case-run \('c1', 0\)"
    ):
        run(case("c1", m("e", 1.0), m("e", 0.0)))


def test_duplicate_evaluator_id_is_rejected_even_when_one_is_an_error() -> None:
    with pytest.raises(ValidationError, match="duplicate evaluator id 'e'"):
        run(case("c1", m("e", 1.0), m("e", None, error="x")))


def test_duplicate_evaluator_id_is_rejected_on_a_failed_task() -> None:
    with pytest.raises(ValidationError, match="duplicate evaluator id 'e'"):
        run(case("c1", m("e", None), m("e", None), task_error="boom"))


def test_same_evaluator_id_in_different_case_runs_is_allowed() -> None:
    result = run(
        case("c1", m("e", 1.0)), case("c1", m("e", 0.0), run_index=1), case("c2", m("e", 1.0))
    )
    assert len(result.cases) == 3


def test_one_display_name_for_two_ids_in_one_case_run_is_allowed() -> None:
    # A display-name collision is a finding (name-collision), not a load error.
    result = run(case("c1", m("strict", 0.0, display="Judge"), m("lenient", 1.0, display="Judge")))
    assert len(result.cases[0].measurements) == 2


def test_conflicting_kinds_for_one_evaluator_id_are_rejected() -> None:
    with pytest.raises(
        ValidationError,
        match=(
            r"evaluator id 'e' has conflicting kinds: 'score' in case-run \('c1', 0\), "
            r"'assertion' in case-run \('c2', 0\)"
        ),
    ):
        run(case("c1", m("e", 1.0)), case("c2", m("e", True, kind="assertion")))


def test_conflicting_kind_on_an_error_measurement_is_rejected() -> None:
    with pytest.raises(ValidationError, match="conflicting kinds"):
        run(case("c1", m("e", "yes", kind="label")), case("c2", m("e", None, error="x")))


def test_conflicting_kinds_across_repeats_are_rejected() -> None:
    with pytest.raises(ValidationError, match="conflicting kinds"):
        run(case("c1", m("e", 1.0)), case("c1", m("e", "a", kind="label"), run_index=1))


def test_one_kind_per_evaluator_id_is_allowed() -> None:
    result = run(
        case("c1", m("a", True, kind="assertion"), m("s", 1.0)),
        case("c2", m("a", None, kind="assertion", error="x"), m("s", 0.5)),
    )
    assert len(result.cases) == 2


def test_measurement_with_both_value_and_error_is_rejected() -> None:
    with pytest.raises(
        ValidationError,
        match=(
            # repr() quotes an id containing single quotes with double quotes.
            r"measurement for evaluator \"Judge\(rubric='strict'\)\" in case-run \('c2', 1\) "
            r"has both a value and an error"
        ),
    ):
        run(
            case("c1", m("Judge(rubric='strict')", 1.0)),
            case("c2", m("Judge(rubric='strict')", 1.0, error="timeout"), run_index=1),
        )


@pytest.mark.parametrize(
    ("value", "kind"),
    [(0.0, "score"), (False, "assertion"), ("", "label")],
    ids=["zero", "false", "empty-label"],
)
def test_falsy_value_with_an_error_is_rejected(value: float | bool | str, kind: Kind) -> None:
    # Exporters that write score=0.0 next to the error message must not count as covered.
    with pytest.raises(ValidationError, match="has both a value and an error"):
        run(case("c1", m("e", value, kind=kind, error="timeout")))


def test_value_with_an_error_is_rejected_on_a_failed_task() -> None:
    with pytest.raises(ValidationError, match="has both a value and an error"):
        run(case("c1", m("e", 0.5, error="x"), task_error="boom"))


def test_value_without_an_error_is_allowed() -> None:
    result = run(case("c1", m("e", 0.0, error=None)))
    assert result.cases[0].measurements[0].value == 0.0


def test_error_without_a_value_is_allowed() -> None:
    result = run(case("c1", m("e", None, error="timeout")))
    assert result.cases[0].measurements[0].error == "timeout"
