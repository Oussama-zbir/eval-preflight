"""Check 7 (only with a baseline): is the candidate run comparable to the baseline?

A score that moved between two runs means little if the runs measured different
cases, different evaluators, different repeat counts, or if the candidate simply
has less evidence. Differences in what was measured WARN (FAIL with
require_same_cases); lower coverage for an evaluator always FAILs.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from eval_preflight.checks._common import covers, eligible, evaluator_ids, listed, pct
from eval_preflight.model import EvalRun
from eval_preflight.report import Finding, Severity

CHECK_ID = "baseline-comparability"


def _difference(label: str, candidate: list[str], baseline: list[str]) -> tuple[str, Any] | None:
    in_candidate, in_baseline = set(candidate), set(baseline)
    added = [x for x in candidate if x not in in_baseline]
    removed = [x for x in baseline if x not in in_candidate]
    if not added and not removed:
        return None
    parts = [f"{verb} {listed(xs)}" for verb, xs in (("added", added), ("removed", removed)) if xs]
    message = f"{label} differ from the baseline: " + "; ".join(parts)
    return message, {"added": added, "removed": removed}


def _coverage(run: EvalRun, evaluator_id: str) -> tuple[int, int]:
    cases = eligible(run)
    return sum(covers(c, evaluator_id) for c in cases), len(cases)


def _fraction(n: int, total: int) -> str:
    return f"{n}/{total} ({pct(n, total)})" if total else f"{n}/{total}"


def check_baseline_comparability(
    run: EvalRun, baseline: EvalRun, *, require_same_cases: bool
) -> list[Finding]:
    findings = []
    set_severity: Severity = "FAIL" if require_same_cases else "WARN"

    case_ids = list(dict.fromkeys(c.case_id for c in run.cases))
    baseline_case_ids = list(dict.fromkeys(c.case_id for c in baseline.cases))
    ids, baseline_ids = evaluator_ids(run), evaluator_ids(baseline)
    for kind, label, candidate, reference in (
        ("cases", "cases", case_ids, baseline_case_ids),
        ("evaluators", "evaluators", ids, baseline_ids),
    ):
        difference = _difference(label, candidate, reference)
        if difference:
            message, details = difference
            findings.append(
                Finding(
                    check=CHECK_ID,
                    severity=set_severity,
                    message=message,
                    details={"kind": kind, **details},
                )
            )

    shared = [i for i in ids if i in set(baseline_ids)]
    for evaluator_id in shared:
        n, total = _coverage(run, evaluator_id)
        base_n, base_total = _coverage(baseline, evaluator_id)
        # Exact fractions: n/total < base_n/base_total. A candidate with no eligible
        # case-runs has coverage 0.
        candidate_rate = (n, total) if total else (0, 1)
        if base_total and candidate_rate[0] * base_total < base_n * candidate_rate[1]:
            findings.append(
                Finding(
                    check=CHECK_ID,
                    severity="FAIL",
                    message=(
                        f"{evaluator_id} coverage dropped from {_fraction(base_n, base_total)} "
                        f"in the baseline to {_fraction(n, total)}"
                    ),
                    details={
                        "kind": "coverage",
                        "evaluator_id": evaluator_id,
                        "baseline_covered": base_n,
                        "baseline_eligible": base_total,
                        "covered": n,
                        "eligible": total,
                    },
                )
            )

    repeats = Counter(c.case_id for c in run.cases)
    baseline_repeats = Counter(c.case_id for c in baseline.cases)
    counts = {
        case_id: [baseline_repeats[case_id], repeats[case_id]]
        for case_id in case_ids
        if case_id in baseline_repeats and baseline_repeats[case_id] != repeats[case_id]
    }
    if counts:
        shown = listed(f"{case_id} {old} → {new}" for case_id, (old, new) in counts.items())
        findings.append(
            Finding(
                check=CHECK_ID,
                severity="WARN",
                message=f"repeat counts differ from the baseline: {shown}",
                details={"kind": "repeats", "counts": counts},
            )
        )

    if not findings:
        findings.append(
            Finding(
                check=CHECK_ID,
                severity="PASS",
                message="same cases, evaluators and repeats as the baseline; no coverage drop",
            )
        )
    return findings
