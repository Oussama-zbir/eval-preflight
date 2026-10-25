import pytest
from pydantic import ValidationError

from eval_preflight import CaseResult, EvalRun, Measurement
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
