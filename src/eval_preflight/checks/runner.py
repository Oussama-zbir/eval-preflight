"""Run every check and collect the findings into a CheckResult."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from eval_preflight.checks.evaluator_coverage import check_evaluator_coverage
from eval_preflight.checks.evaluator_errors import check_evaluator_errors
from eval_preflight.checks.name_collision import check_name_collision
from eval_preflight.checks.task_failures import check_task_failures
from eval_preflight.model import EvalRun
from eval_preflight.report import CheckResult


class CheckConfig(BaseModel):
    """Thresholds. Defaults are deliberately strict (SPEC.md §6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_coverage: float = Field(default=1.0, ge=0.0, le=1.0, allow_inf_nan=False)
    max_evaluator_error_rate: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    max_task_failure_rate: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)


def check(run: EvalRun, config: CheckConfig | None = None) -> CheckResult:
    config = config or CheckConfig()
    findings = [
        *check_task_failures(run, max_rate=config.max_task_failure_rate),
        *check_evaluator_coverage(run, min_coverage=config.min_coverage),
        *check_evaluator_errors(run, max_rate=config.max_evaluator_error_rate),
        *check_name_collision(run),
    ]
    return CheckResult(run=run, findings=findings)
