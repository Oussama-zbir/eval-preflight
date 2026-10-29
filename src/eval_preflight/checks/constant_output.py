"""Check 6: a score or label evaluator that returned one value on every case-run.

Counts the eligible case-runs where the evaluator produced a finite value, so gaps
do not disable the check. Assertions are exempt: an assertion that passes
everywhere is the goal, not a stuck judge (SPEC §15).
"""

from __future__ import annotations

from eval_preflight.checks._common import eligible, evaluator_ids, has_value
from eval_preflight.model import EvalRun
from eval_preflight.report import Finding

CHECK_ID = "constant-output"


def check_constant_output(run: EvalRun, *, min_cases: int) -> list[Finding]:
    cases = eligible(run)
    findings = []
    for evaluator_id in evaluator_ids(run):
        values = [
            [
                m.value
                for m in c.measurements
                if m.evaluator.id == evaluator_id
                and m.evaluator.kind != "assertion"
                and has_value(m)
            ]
            for c in cases
        ]
        with_value = [vs for vs in values if vs]
        flat = [v for vs in with_value for v in vs]
        # Numeric equality on purpose: 1 and 1.0 are the same score.
        if len(with_value) < min_cases or any(v != flat[0] for v in flat):
            continue
        n, total = len(with_value), len(cases)
        scope = (
            f"all {n} case-runs"
            if n == total
            else f"all {n} case-runs with a value (of {total} eligible)"
        )
        findings.append(
            Finding(
                check=CHECK_ID,
                severity="WARN",
                message=f"{evaluator_id} returned {flat[0]!r} on {scope}",
                details={
                    "evaluator_id": evaluator_id,
                    "value": repr(flat[0]),
                    "case_runs_with_value": n,
                    "eligible": total,
                    "min_cases": min_cases,
                },
            )
        )
    if not findings:
        findings.append(
            Finding(
                check=CHECK_ID,
                severity="PASS",
                message=(
                    f"no score or label evaluator returned a single value on ≥{min_cases} case-runs"
                ),
                details={"min_cases": min_cases},
            )
        )
    return findings
