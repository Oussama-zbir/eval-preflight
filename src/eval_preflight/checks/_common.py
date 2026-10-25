"""Helpers shared by the checks: case-run labels, eligibility, rates."""

from __future__ import annotations

import math
from collections.abc import Iterable

from eval_preflight.model import CaseResult, EvalRun

MAX_LISTED = 5


def labeller(run: EvalRun) -> dict[tuple[str, int], str]:
    """Label each case-run; the run index is shown only when the run has repeats."""
    repeated = any(c.run_index > 0 for c in run.cases)
    return {
        (c.case_id, c.run_index): f"{c.case_id}[{c.run_index}]" if repeated else c.case_id
        for c in run.cases
    }


def eligible(run: EvalRun) -> list[CaseResult]:
    """Case-runs whose task did not fail: the denominator for evaluator checks."""
    return [c for c in run.cases if c.task_error is None]


def evaluator_ids(run: EvalRun) -> list[str]:
    """Every evaluator id in the run, in order of first appearance."""
    seen: dict[str, None] = {}
    for case in run.cases:
        for m in case.measurements:
            seen.setdefault(m.evaluator.id)
    return list(seen)


def pct(n: int, total: int) -> str:
    """A percentage that never rounds a partial count up to 100% or down to 0%."""
    if n == total:
        return "100%"
    if n == 0:
        return "0%"
    value = math.floor(1000 * n / total) / 10
    if value == 0:
        return "<0.1%"
    return f"{value:g}%"


def listed(labels: Iterable[str]) -> str:
    items = list(labels)
    text = ", ".join(items[:MAX_LISTED])
    if len(items) > MAX_LISTED:
        text += f" (+{len(items) - MAX_LISTED} more)"
    return text
