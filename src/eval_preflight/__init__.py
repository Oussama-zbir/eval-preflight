"""eval-preflight: check that an LLM eval run is complete and attributed correctly."""

from eval_preflight.adapters import LoadError
from eval_preflight.adapters.registry import load
from eval_preflight.checks.runner import CheckConfig, check
from eval_preflight.model import CaseResult, EvalRun, EvaluatorRef, Kind, Measurement
from eval_preflight.report import CheckResult, Finding, IntegrityError, Severity, render

__version__ = "0.0.1"

__all__ = [
    "CaseResult",
    "CheckConfig",
    "CheckResult",
    "EvalRun",
    "EvaluatorRef",
    "Finding",
    "IntegrityError",
    "Kind",
    "LoadError",
    "Measurement",
    "Severity",
    "__version__",
    "check",
    "load",
    "render",
]
