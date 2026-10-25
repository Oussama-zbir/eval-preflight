"""Check 4: display names that do not map one-to-one onto evaluator ids.

Only measurements that carry a value count: the question is which evaluator's
number was filed under which name. A failed evaluator keeps its display name but
filed nothing, so it cannot shift a score.
"""

from __future__ import annotations

from eval_preflight.checks._common import labeller, listed
from eval_preflight.model import EvalRun
from eval_preflight.report import Finding

CHECK_ID = "name-collision"


def _quoted(name: str) -> str:
    return f'"{name}"'


def _describe(head: str, mapping: dict[str, list[str]], *, quote_keys: bool) -> str:
    parts = [
        f"{_quoted(key) if quote_keys else key} on {listed(labels)}"
        for key, labels in mapping.items()
    ]
    return f"{head} → " + "; ".join(parts)


def check_name_collision(run: EvalRun) -> list[Finding]:
    labels = labeller(run)
    by_name: dict[str, dict[str, list[str]]] = {}
    by_id: dict[str, dict[str, list[str]]] = {}
    for c in run.cases:
        label = labels[(c.case_id, c.run_index)]
        for m in c.measurements:
            if m.value is None:
                continue
            ref = m.evaluator
            by_name.setdefault(ref.display_name, {}).setdefault(ref.id, []).append(label)
            by_id.setdefault(ref.id, {}).setdefault(ref.display_name, []).append(label)

    findings = [
        Finding(
            check=CHECK_ID,
            severity="FAIL",
            message=_describe(_quoted(name), ids, quote_keys=False),
            details={"kind": "display_name_to_ids", "display_name": name, "mapping": ids},
        )
        for name, ids in by_name.items()
        if len(ids) > 1
    ]
    findings += [
        Finding(
            check=CHECK_ID,
            severity="FAIL",
            message=_describe(evaluator_id, names, quote_keys=True),
            details={"kind": "id_to_display_names", "evaluator_id": evaluator_id, "mapping": names},
        )
        for evaluator_id, names in by_id.items()
        if len(names) > 1
    ]
    if not findings:
        findings.append(
            Finding(
                check=CHECK_ID,
                severity="PASS",
                message="every display name maps to exactly one evaluator id",
            )
        )
    return findings
