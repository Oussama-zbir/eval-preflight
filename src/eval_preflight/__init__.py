"""eval-preflight: check that an LLM eval run is complete and attributed correctly."""

from eval_preflight.adapters import LoadError
from eval_preflight.adapters.pydantic_evals import from_pydantic_evals
from eval_preflight.adapters.registry import load
from eval_preflight.checks.runner import CheckConfig, check, check_pydantic_evals
from eval_preflight.model import CaseResult, EvalRun, EvaluatorRef, Kind, Measurement
from eval_preflight.report import CheckResult, Finding, IntegrityError, Severity, render

__version__ = "0.0.2"

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
    "check_pydantic_evals",
    "from_pydantic_evals",
    "load",
    "render",
]
