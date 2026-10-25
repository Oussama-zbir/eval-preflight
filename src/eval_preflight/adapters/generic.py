"""Generic input format (docs/input-format.md): JSON document or JSONL of case results.

The on-disk shape flattens measurements[].evaluator into evaluator_id,
display_name and kind. Parsing is strict: unknown fields are errors.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eval_preflight.adapters import LoadError
from eval_preflight.model import CaseResult, EvalRun, EvaluatorRef, Kind, Measurement


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _GenericMeasurement(_Strict):
    evaluator_id: str
    display_name: str
    kind: Kind
    value: float | bool | str | None
    error: str | None = None


class _GenericCase(_Strict):
    case_id: str
    run_index: int = Field(default=0, ge=0)
    task_error: str | None = None
    measurements: list[_GenericMeasurement] = Field(default_factory=list)

    def to_case(self) -> CaseResult:
        return CaseResult(
            case_id=self.case_id,
            run_index=self.run_index,
            task_error=self.task_error,
            measurements=[
                Measurement(
                    evaluator=EvaluatorRef(
                        id=m.evaluator_id, display_name=m.display_name, kind=m.kind
                    ),
                    value=m.value,
                    error=m.error,
                )
                for m in self.measurements
            ],
        )


class _GenericDocument(_Strict):
    name: str
    source: str
    source_version: str | None = None
    cases: list[_GenericCase]
    reported_aggregates: dict[str, float] | None = None


def looks_generic(document: object) -> bool:
    """A JSON object with source "generic", or a case result (the first JSONL line)."""
    return isinstance(document, dict) and (
        document.get("source") == "generic" or "case_id" in document
    )


def parse_generic(text: str, *, default_name: str) -> EvalRun:
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        document = None
    if isinstance(document, dict) and "case_id" not in document:
        run = _parse_document(document)
    else:
        run = _parse_jsonl(text, default_name=default_name)
    if not run.cases:
        raise LoadError("no case results in input")
    return run


def _parse_document(document: dict[str, Any]) -> EvalRun:
    if document.get("source") != "generic":
        raise LoadError(f"source must be 'generic', got {document.get('source')!r}")
    try:
        parsed = _GenericDocument.model_validate(document)
    except ValidationError as exc:
        raise LoadError(f"invalid generic document: {exc}") from exc
    return _build(
        name=parsed.name,
        source=parsed.source,
        source_version=parsed.source_version,
        cases=[c.to_case() for c in parsed.cases],
        reported_aggregates=parsed.reported_aggregates,
    )


def _parse_jsonl(text: str, *, default_name: str) -> EvalRun:
    cases = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LoadError(f"line {number}: not valid JSON ({exc.msg})") from exc
        if not isinstance(row, dict):
            raise LoadError(f"line {number}: expected a JSON object")
        try:
            cases.append(_GenericCase.model_validate(row).to_case())
        except ValidationError as exc:
            raise LoadError(f"line {number}: {exc}") from exc
    return _build(name=default_name, source="generic", cases=cases)


def _build(**fields: Any) -> EvalRun:
    try:
        return EvalRun(**fields)
    except ValidationError as exc:
        raise LoadError(str(exc)) from exc
