"""Check 5: do the two ways of averaging a score agree, and is the reported number reproducible?

Two estimators over the numeric values of eligible case-runs:

- pooled: the mean of every value;
- mean of per-case means: average within each case_id (over repeats), then across cases.

They differ only when cases contribute unequal numbers of values (repeats with gaps, several
assertions per case). NaN and ±inf are excluded from both (SPEC §15, amendment 3).
pydantic-evals uses the pooled mean for single runs and the mean of per-case means for
repeated runs, so a reported number is checked against both.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable

from eval_preflight.checks._common import eligible, evaluator_ids, has_value
from eval_preflight.model import EvalRun, Measurement
from eval_preflight.report import Finding, Severity

CHECK_ID = "aggregation-consistency"
ASSERTIONS = "assertions"

_Values = dict[str, list[float]]  # case_id -> numeric values, in case-run order


def _numeric(m: Measurement) -> float | None:
    # NaN/inf are excluded from both estimators; evaluator-coverage flags them.
    value = m.value
    if m.evaluator.kind == "label" or not isinstance(value, bool | float) or not has_value(m):
        return None
    return float(value)


def _collect(run: EvalRun, keep: Callable[[Measurement], bool]) -> _Values:
    values: _Values = defaultdict(list)
    for c in eligible(run):
        for m in c.measurements:
            if keep(m) and (value := _numeric(m)) is not None:
                values[c.case_id].append(value)
    return values


def _has_id(evaluator_id: str) -> Callable[[Measurement], bool]:
    return lambda m: m.evaluator.id == evaluator_id


def _pooled(values: _Values) -> float:
    flat = [v for vs in values.values() for v in vs]
    return math.fsum(flat) / len(flat)


def _mean_of_cases(values: _Values) -> float:
    return math.fsum(math.fsum(vs) / len(vs) for vs in values.values()) / len(values)


def _close(a: float, b: float, tolerance: float) -> bool:
    return math.isclose(a, b, rel_tol=tolerance, abs_tol=tolerance)


def _fmt(value: float) -> str:
    return f"{value:.6g}"


def _estimator_finding(
    subject: str, values: _Values, details: dict[str, object], *, tolerance: float, strict: bool
) -> Finding:
    pooled, by_case = _pooled(values), _mean_of_cases(values)
    details |= {
        "pooled": pooled,
        "mean_of_cases": by_case,
        "values": sum(len(vs) for vs in values.values()),
        "cases": len(values),
        "tolerance": tolerance,
    }
    severity: Severity
    if _close(pooled, by_case, tolerance):
        message, severity = f"{subject}: pooled = mean of per-case means = {_fmt(pooled)}", "PASS"
    else:
        message = f"{subject}: pooled mean {_fmt(pooled)} vs mean of per-case means {_fmt(by_case)}"
        severity = "FAIL" if strict else "WARN"
    return Finding(check=CHECK_ID, severity=severity, message=message, details=details)


def _reported_finding(run: EvalRun, key: str, reported: float, *, tolerance: float) -> Finding:
    values = _collect(run, lambda m: m.evaluator.display_name == key)
    if not values and key == ASSERTIONS:
        values = _collect(run, lambda m: m.evaluator.kind == "assertion")
    subject = f'reported "{key}" = {_fmt(reported)}'
    details: dict[str, object] = {"reported_key": key, "reported": reported}

    if not values:
        return Finding(
            check=CHECK_ID,
            severity="WARN",
            message=f"{subject} cannot be checked: no numeric values filed under that name",
            details=details | {"reproduced_by": None},
        )

    pooled, by_case = _pooled(values), _mean_of_cases(values)
    matches = [
        name
        for name, value in (("pooled", pooled), ("mean_of_cases", by_case))
        if _close(reported, value, tolerance)
    ]
    n_cases = len({c.case_id for c in eligible(run)})
    details |= {
        "pooled": pooled,
        "mean_of_cases": by_case,
        "reproduced_by": matches[0] if len(matches) == 1 else ("both" if matches else None),
        "cases_with_values": len(values),
        "eligible_cases": n_cases,
        "tolerance": tolerance,
    }
    source = f"from {len(values)} of {n_cases} cases"
    if not matches:
        message = (
            f"{subject} matches neither pooled mean {_fmt(pooled)} "
            f"nor mean of per-case means {_fmt(by_case)}"
        )
        return Finding(check=CHECK_ID, severity="FAIL", message=message, details=details)
    if len(matches) == 2:
        message = f"{subject} reproduced {source}"
    elif matches == ["pooled"]:
        message = (
            f"{subject} reproduced as the pooled mean {source} "
            f"(mean of per-case means: {_fmt(by_case)})"
        )
    else:
        message = (
            f"{subject} reproduced as the mean of per-case means {source} "
            f"(pooled mean: {_fmt(pooled)})"
        )
    return Finding(check=CHECK_ID, severity="PASS", message=message, details=details)


def check_aggregation_consistency(run: EvalRun, *, tolerance: float, strict: bool) -> list[Finding]:
    findings = []
    for evaluator_id in evaluator_ids(run):
        values = _collect(run, _has_id(evaluator_id))
        if values:
            findings.append(
                _estimator_finding(
                    evaluator_id,
                    values,
                    {"evaluator_id": evaluator_id, "group": None},
                    tolerance=tolerance,
                    strict=strict,
                )
            )

    assertions = _collect(run, lambda m: m.evaluator.kind == "assertion")
    if assertions:
        findings.append(
            _estimator_finding(
                "all assertions",
                assertions,
                {"evaluator_id": None, "group": ASSERTIONS},
                tolerance=tolerance,
                strict=strict,
            )
        )

    for key, reported in (run.reported_aggregates or {}).items():
        findings.append(_reported_finding(run, key, reported, tolerance=tolerance))
    return findings
