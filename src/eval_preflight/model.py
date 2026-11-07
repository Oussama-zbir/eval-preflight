"""Canonical data model (SPEC.md §5). Every adapter produces an EvalRun.

Evaluator identity is EvaluatorRef.id. Display names are data to be checked, not
trusted. A case-run is the pair (case_id, run_index).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal["score", "assertion", "label"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluatorRef(_Model):
    id: str
    display_name: str
    kind: Kind


class Measurement(_Model):
    evaluator: EvaluatorRef
    value: float | bool | str | None
    error: str | None = None


class CaseResult(_Model):
    case_id: str
    run_index: int = Field(default=0, ge=0)
    task_error: str | None = None
    measurements: list[Measurement] = Field(default_factory=list)


class EvalRun(_Model):
    name: str
    source: str
    source_version: str | None = None
    cases: list[CaseResult]
    reported_aggregates: dict[str, float] | None = None

    @model_validator(mode="after")
    def _case_runs_are_unique(self) -> EvalRun:
        seen: set[tuple[str, int]] = set()
        for case in self.cases:
            key = (case.case_id, case.run_index)
            if key in seen:
                raise ValueError(f"duplicate case-run {key!r}")
            seen.add(key)
        return self

    @model_validator(mode="after")
    def _evaluator_ids_are_unambiguous(self) -> EvalRun:
        # SPEC §15, amendment 4: one measurement per evaluator id per case-run, and one
        # kind per evaluator id across the run. Either would otherwise change a verdict
        # silently (a duplicate pools like a repeat; a mixed kind splits the checks).
        kinds: dict[str, tuple[Kind, tuple[str, int]]] = {}
        for case in self.cases:
            key = (case.case_id, case.run_index)
            ids: set[str] = set()
            for measurement in case.measurements:
                ref = measurement.evaluator
                if ref.id in ids:
                    raise ValueError(f"duplicate evaluator id {ref.id!r} in case-run {key!r}")
                ids.add(ref.id)
                first = kinds.setdefault(ref.id, (ref.kind, key))
                if first[0] != ref.kind:
                    raise ValueError(
                        f"evaluator id {ref.id!r} has conflicting kinds: "
                        f"{first[0]!r} in case-run {first[1]!r}, {ref.kind!r} in case-run {key!r}"
                    )
        return self
