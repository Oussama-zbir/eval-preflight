"""Check results: findings, the overall verdict, and terminal rendering."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from rich.console import Console
from rich.markup import escape

from eval_preflight.model import EvalRun

Severity = Literal["PASS", "WARN", "FAIL"]


class Finding(BaseModel):
    check: str
    severity: Severity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class IntegrityError(Exception):
    """Raised by CheckResult.raise_if_failed; carries the FAIL findings."""

    def __init__(self, findings: list[Finding]) -> None:
        self.findings = findings
        lines = "\n".join(f"{f.check}: {f.message}" for f in findings)
        super().__init__(f"eval run failed {len(findings)} integrity check(s):\n{lines}")


def _summary(run: EvalRun) -> dict[str, Any]:
    return {
        "name": run.name,
        "source": run.source,
        "source_version": run.source_version,
        "cases": len({c.case_id for c in run.cases}),
        "case_runs": len(run.cases),
        "evaluators": list(
            dict.fromkeys(m.evaluator.id for c in run.cases for m in c.measurements)
        ),
    }


class CheckResult(BaseModel):
    run: EvalRun
    findings: list[Finding]
    baseline: EvalRun | None = None

    @property
    def verdict(self) -> Severity:
        severities = {f.severity for f in self.findings}
        if "FAIL" in severities:
            return "FAIL"
        if "WARN" in severities:
            return "WARN"
        return "PASS"

    def by_check(self, check_id: str) -> list[Finding]:
        return [f for f in self.findings if f.check == check_id]

    def exit_code(self, *, warnings_as_errors: bool = False) -> int:
        """CLI exit code: 1 on FAIL (or WARN with warnings_as_errors), else 0."""
        if self.verdict == "FAIL" or (self.verdict == "WARN" and warnings_as_errors):
            return 1
        return 0

    def to_json(self, *, indent: int | None = 2) -> str:
        """The machine-readable report: {"verdict", "run", "findings"}.

        Always valid JSON: non-finite floats in details become null (pydantic's JSON
        mode), and allow_nan=False guards the rest.
        """
        run = _summary(self.run) | {"baseline": _summary(self.baseline) if self.baseline else None}
        document = {
            "verdict": self.verdict,
            "run": run,
            "findings": [f.model_dump(mode="json") for f in self.findings],
        }
        return json.dumps(document, indent=indent, ensure_ascii=False, allow_nan=False)

    def raise_if_failed(self) -> None:
        failures = [f for f in self.findings if f.severity == "FAIL"]
        if failures:
            raise IntegrityError(failures)


_STYLE: dict[Severity, str] = {"PASS": "green", "WARN": "yellow", "FAIL": "bold red"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def render(result: CheckResult, console: Console, *, quiet: bool = False) -> None:
    """Print the one-screen summary. quiet keeps only non-PASS findings and the verdict."""
    run = result.run
    if not quiet:
        n_cases = len({c.case_id for c in run.cases})
        parts = [run.name, _plural(n_cases, "case")]
        if len(run.cases) != n_cases:
            parts.append(_plural(len(run.cases), "case-run"))
        parts.append(" ".join(p for p in (run.source, run.source_version) if p))
        console.print(escape("eval-preflight  " + " · ".join(parts)), highlight=False)
        console.print()

    shown = [f for f in result.findings if not (quiet and f.severity == "PASS")]
    for finding in shown:
        style = _STYLE[finding.severity]
        console.print(
            f"[{style}]{finding.severity}[/]  {escape(f'{finding.check:<24}{finding.message}')}",
            highlight=False,
        )

    failures = sum(f.severity == "FAIL" for f in result.findings)
    warnings = sum(f.severity == "WARN" for f in result.findings)
    if shown:
        console.print()
    verdict = result.verdict
    console.print(
        f"Verdict: [{_STYLE[verdict]}]{verdict}[/] "
        f"({_plural(failures, 'failure')}, {_plural(warnings, 'warning')})",
        highlight=False,
    )
