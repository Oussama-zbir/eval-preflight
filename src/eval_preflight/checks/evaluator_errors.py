"""Check 3: per evaluator id, the share of eligible case-runs where it errored."""

from __future__ import annotations

from collections import Counter

from eval_preflight.checks._common import eligible, evaluator_ids, labeller
from eval_preflight.model import EvalRun
from eval_preflight.report import Finding, Severity

CHECK_ID = "evaluator-errors"


def check_evaluator_errors(run: EvalRun, *, max_rate: float) -> list[Finding]:
    labels = labeller(run)
    cases = eligible(run)
    findings = []
    for evaluator_id in evaluator_ids(run):
        # Counter keeps insertion order, so most_common breaks ties on first seen.
        counts: Counter[str] = Counter()
        errored = []
        for c in cases:
            errors = [
                m.error
                for m in c.measurements
                if m.evaluator.id == evaluator_id and m.error is not None
            ]
            if errors:
                errored.append(labels[(c.case_id, c.run_index)])
                counts.update(errors)

        total = len(cases)
        rate = len(errored) / total if total else 0.0
        message = f"{evaluator_id} errored on {len(errored)}/{total}"
        details = {
            "evaluator_id": evaluator_id,
            "errored": len(errored),
            "eligible": total,
            "rate": rate,
            "threshold": max_rate,
            "errored_case_runs": errored,
            "error_counts": dict(counts),
            "most_common_error": None,
        }
        if counts:
            details["most_common_error"] = most_common = counts.most_common(1)[0][0]
            message += f": {most_common}"
        severity: Severity = "FAIL" if rate > max_rate else "PASS"
        findings.append(
            Finding(check=CHECK_ID, severity=severity, message=message, details=details)
        )
    return findings
