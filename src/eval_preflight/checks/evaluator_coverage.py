"""Check 2: per evaluator id, the share of eligible case-runs with a value.

NaN and ±inf are not values: they do not count as covered, and any evaluator that
returned one gets its own "non-finite value" FAIL finding (SPEC §15, amendment 3).
"""

from __future__ import annotations

from eval_preflight.checks._common import (
    eligible,
    evaluator_ids,
    has_value,
    is_non_finite,
    labeller,
    listed,
    pct,
)
from eval_preflight.model import EvalRun
from eval_preflight.report import Finding, Severity

CHECK_ID = "evaluator-coverage"


def check_evaluator_coverage(run: EvalRun, *, min_coverage: float) -> list[Finding]:
    ids = evaluator_ids(run)
    if not ids:
        return [
            Finding(
                check=CHECK_ID,
                severity="FAIL",
                message="no evaluator produced a measurement on any case-run",
            )
        ]

    labels = labeller(run)
    cases = eligible(run)
    findings = []
    for evaluator_id in ids:
        uncovered = [
            labels[(c.case_id, c.run_index)]
            for c in cases
            if not any(m.evaluator.id == evaluator_id and has_value(m) for m in c.measurements)
        ]
        n, total = len(cases) - len(uncovered), len(cases)
        details = {
            "evaluator_id": evaluator_id,
            "covered": n,
            "eligible": total,
            "coverage": n / total if total else None,
            "threshold": min_coverage,
            "uncovered_case_runs": uncovered,
        }
        severity: Severity
        if total == 0:
            message, severity = f"{evaluator_id} has no eligible case-runs", "FAIL"
        else:
            message = f"{evaluator_id} scored {n}/{total} case-runs ({pct(n, total)})"
            severity = "FAIL" if n / total < min_coverage else "PASS"
        findings.append(
            Finding(check=CHECK_ID, severity=severity, message=message, details=details)
        )

        non_finite = {
            labels[(c.case_id, c.run_index)]: [
                repr(m.value)
                for m in c.measurements
                if m.evaluator.id == evaluator_id and is_non_finite(m)
            ]
            for c in cases
        }
        non_finite = {label: values for label, values in non_finite.items() if values}
        if non_finite:
            values = list(dict.fromkeys(v for vs in non_finite.values() for v in vs))
            findings.append(
                Finding(
                    check=CHECK_ID,
                    severity="FAIL",
                    message=(
                        f"{evaluator_id} returned a non-finite value on "
                        f"{len(non_finite)}/{total} case-runs: {listed(values)}"
                    ),
                    details={
                        "kind": "non_finite",
                        "evaluator_id": evaluator_id,
                        "non_finite_case_runs": list(non_finite),
                        # Strings: NaN/inf are not valid JSON numbers.
                        "values": values,
                    },
                )
            )
    return findings
