"""Check 1: case-runs where the task under test raised."""

from __future__ import annotations

from collections import Counter

from eval_preflight.checks._common import labeller, pct
from eval_preflight.model import EvalRun
from eval_preflight.report import Finding, Severity

CHECK_ID = "task-failures"


def check_task_failures(run: EvalRun, *, max_rate: float) -> list[Finding]:
    total = len(run.cases)
    if total == 0:
        return [
            Finding(
                check=CHECK_ID,
                severity="FAIL",
                message="run contains no case-runs",
                details={"failed": 0, "total": 0, "threshold": max_rate},
            )
        ]

    labels = labeller(run)
    failed = [c for c in run.cases if c.task_error is not None]
    rate = len(failed) / total
    details = {
        "failed": len(failed),
        "total": total,
        "rate": rate,
        "threshold": max_rate,
        "failed_case_runs": [labels[(c.case_id, c.run_index)] for c in failed],
    }
    message = f"{len(failed)}/{total}"
    if failed:
        counts = Counter(c.task_error for c in failed)
        details["most_common_error"] = counts.most_common(1)[0][0]
        message = (
            f"{len(failed)}/{total} case-runs ({pct(len(failed), total)}) raised: "
            f"{details['most_common_error']}"
        )
    severity: Severity = "FAIL" if rate > max_rate else "PASS"
    return [Finding(check=CHECK_ID, severity=severity, message=message, details=details)]
