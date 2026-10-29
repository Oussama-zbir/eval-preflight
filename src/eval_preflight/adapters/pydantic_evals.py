"""pydantic-evals adapter: an EvaluationReport serialized to JSON (SPEC.md §7.2).

The input is what `TypeAdapter(EvaluationReport).dump_json(report, by_alias=True)`
writes. Parsing reads only the fields the mapping needs and ignores the rest
(inputs, outputs, durations, stack traces), so pydantic-evals is not required.

Evaluator identity comes from each result's `source` (the evaluator's class name
and serialization arguments), never from the dict key it is filed under: the key
is the display name that pydantic-evals deduplicates per case (#10636). An
evaluator that returns a dict of named outputs yields one id per output name.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from eval_preflight.adapters import LoadError
from eval_preflight.model import CaseResult, EvalRun, EvaluatorRef, Kind, Measurement

SOURCE = "pydantic-evals"
_REPEAT_SUFFIX = re.compile(r" \[(\d+)/(\d+)\]$")
_SECTIONS: tuple[tuple[str, Kind], ...] = (
    ("scores", "score"),
    ("assertions", "assertion"),
    ("labels", "label"),
)


class _Source(BaseModel):
    name: str
    arguments: list[Any] | dict[str, Any] | None = None


class _Result(BaseModel):
    name: str
    value: float | bool | str
    source: _Source | None = None


class _EvaluatorFailure(BaseModel):
    name: str
    error_message: str
    error_type: str | None = None
    source: _Source | None = None


class _Case(BaseModel):
    name: str
    source_case_name: str | None = None
    scores: dict[str, _Result] = {}
    assertions: dict[str, _Result] = {}
    labels: dict[str, _Result] = {}
    evaluator_failures: list[_EvaluatorFailure] = []


class _Failure(BaseModel):
    name: str
    source_case_name: str | None = None
    error_message: str


class _Report(BaseModel):
    name: str
    dataset_name: str | None = None
    cases: list[_Case]
    failures: list[_Failure] = []


def looks_pydantic_evals(document: object) -> bool:
    """A JSON object with the report's `cases` and `failures` lists and no generic source."""
    return (
        isinstance(document, dict)
        and document.get("source") != "generic"
        and isinstance(document.get("cases"), list)
        and isinstance(document.get("failures"), list)
    )


def evaluator_id(source: _Source, output_name: str) -> str:
    """Canonical identity: `Name(key=repr(value), ...)` with sorted keys (SPEC §7.2).

    pydantic-evals (`BaseEvaluator.as_spec`) serializes non-default fields only: none
    as null, several as a dict, and a single one that is the first dataclass field
    as a one-element list without its name. That name is not in the report, so the
    value is rendered positionally, `Judge('strict')`, rather than under a guessed key.

    A result whose name differs from the evaluator's name is a named output of a
    multi-output evaluator and gets its own id, `Name(...)[output]`.
    """
    arguments = source.arguments
    if not arguments:
        rendered: list[str] = []
    elif isinstance(arguments, dict):
        rendered = [f"{key}={_render(arguments[key])}" for key in sorted(arguments)]
    else:
        rendered = [_render(value) for value in arguments]
    base = f"{source.name}({', '.join(rendered)})"
    return base if output_name == source.name else f"{base}[{output_name}]"


def parse_pydantic_evals(text: str, *, default_name: str) -> EvalRun:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LoadError(f"pydantic-evals report is not valid JSON ({exc.msg})") from exc
    if not looks_pydantic_evals(document):
        raise LoadError("not a pydantic-evals report: expected an object with cases and failures")
    try:
        report = _Report.model_validate(document)
    except ValidationError as exc:
        raise LoadError(f"invalid pydantic-evals report: {exc}") from exc

    known_kinds = _known_kinds(report.cases)
    cases = [_case(c, known_kinds) for c in report.cases]
    cases += [
        CaseResult(
            case_id=case_id,
            run_index=run_index,
            task_error=failure.error_message,
        )
        for failure in report.failures
        for case_id, run_index in [_case_run(failure.name, failure.source_case_name)]
    ]
    if not cases:
        raise LoadError("no case results in input")
    try:
        return EvalRun(
            name=report.dataset_name or report.name or default_name,
            source=SOURCE,
            cases=cases,
        )
    except ValidationError as exc:
        raise LoadError(str(exc)) from exc


def _render(value: Any) -> str:
    """repr() of a JSON value, with dict keys sorted at every level."""
    if isinstance(value, dict):
        items = ", ".join(f"{key!r}: {_render(value[key])}" for key in sorted(value))
        return f"{{{items}}}"
    if isinstance(value, list):
        return f"[{', '.join(_render(item) for item in value)}]"
    return repr(value)


def _require_source(source: _Source | None, case_name: str, display_name: str) -> _Source:
    # SPEC §7.2 identity guard: without source metadata the attribution cannot be
    # verified, and guessing it from the display key is the bug we exist to catch.
    if source is None:
        raise LoadError(
            f"case {case_name!r}: evaluator {display_name!r} has no source metadata; "
            "its identity cannot be verified"
        )
    return source


def _known_kinds(cases: list[_Case]) -> dict[str, Kind]:
    kinds: dict[str, Kind] = {}
    for case in cases:
        for section, kind in _SECTIONS:
            for key, result in getattr(case, section).items():
                source = _require_source(result.source, case.name, key)
                kinds[evaluator_id(source, result.name)] = kind
    return kinds


def _case(case: _Case, known_kinds: dict[str, Kind]) -> CaseResult:
    case_id, run_index = _case_run(case.name, case.source_case_name)
    measurements = []
    for section, kind in _SECTIONS:
        for key, result in getattr(case, section).items():
            source = _require_source(result.source, case.name, key)
            ref = EvaluatorRef(id=evaluator_id(source, result.name), display_name=key, kind=kind)
            measurements.append(Measurement(evaluator=ref, value=result.value))
    for failure in case.evaluator_failures:
        # A failure carries the evaluator's own name: a scalar evaluator's results use the
        # same name, so they share an id; a multi-output evaluator's outputs are unknown.
        source = _require_source(failure.source, case.name, failure.name)
        identity = evaluator_id(source, failure.name)
        ref = EvaluatorRef(
            id=identity,
            display_name=failure.name,
            # A failure does not say which section the evaluator writes to (SPEC §7.2).
            kind=known_kinds.get(identity, "score"),
        )
        measurements.append(Measurement(evaluator=ref, value=None, error=_error(failure)))
    return CaseResult(case_id=case_id, run_index=run_index, measurements=measurements)


def _error(failure: _EvaluatorFailure) -> str:
    # pydantic-evals 2.x already prefixes error_message with the exception type
    # ("RuntimeError: judge quota exhausted"); add the type only when it is missing.
    message, error_type = failure.error_message, failure.error_type
    if error_type and not message.startswith(f"{error_type}:"):
        return f"{error_type}: {message}"
    return message


def _case_run(name: str, source_case_name: str | None) -> tuple[str, int]:
    """(case_id, run_index): repeats are named "<case> [i/n]" with a 1-based i."""
    if source_case_name is None:
        return name, 0
    match = _REPEAT_SUFFIX.search(name)
    if match is None or name[: match.start()] != source_case_name:
        raise LoadError(
            f"case {name!r}: has source_case_name {source_case_name!r} "
            "but no matching ' [i/n]' repeat suffix"
        )
    index, total = int(match.group(1)), int(match.group(2))
    if not 1 <= index <= total:
        raise LoadError(f"case {name!r}: repeat index {index} outside 1..{total}")
    return source_case_name, index - 1
