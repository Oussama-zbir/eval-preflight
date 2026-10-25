"""Small constructors that keep test runs readable."""

from __future__ import annotations

from eval_preflight import CaseResult, EvalRun, EvaluatorRef, Kind, Measurement


def m(
    evaluator_id: str,
    value: float | bool | str | None,
    *,
    display: str | None = None,
    kind: Kind = "score",
    error: str | None = None,
) -> Measurement:
    ref = EvaluatorRef(id=evaluator_id, display_name=display or evaluator_id, kind=kind)
    return Measurement(evaluator=ref, value=value, error=error)


def case(
    case_id: str,
    *measurements: Measurement,
    run_index: int = 0,
    task_error: str | None = None,
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        run_index=run_index,
        task_error=task_error,
        measurements=list(measurements),
    )


def run(*cases: CaseResult, name: str = "test") -> EvalRun:
    return EvalRun(name=name, source="generic", cases=list(cases))
