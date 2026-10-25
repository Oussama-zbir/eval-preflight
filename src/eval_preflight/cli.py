"""Command line: eval-preflight check RESULTS [options]. Exit 0 PASS/WARN, 1 FAIL, 2 usage."""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence

from rich.console import Console

from eval_preflight import __version__
from eval_preflight.adapters import LoadError
from eval_preflight.adapters.registry import FORMATS, load
from eval_preflight.checks.runner import CheckConfig, check
from eval_preflight.report import render


def _rate(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {raw!r}") from None
    if math.isnan(value) or not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError(f"must be between 0 and 1, got {raw!r}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eval-preflight",
        description="Check that an eval run is complete and aggregated correctly "
        "before you trust its numbers.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("check", help="check one results file")
    run.add_argument("results", metavar="RESULTS", help="results file (JSON or JSONL)")
    run.add_argument("--format", choices=FORMATS, default="auto")
    run.add_argument(
        "--min-coverage",
        type=_rate,
        default=1.0,
        metavar="RATE",
        help="fail an evaluator below this coverage (default: 1.0)",
    )
    run.add_argument(
        "--max-evaluator-error-rate",
        type=_rate,
        default=0.0,
        metavar="RATE",
        help="fail an evaluator above this error rate (default: 0.0)",
    )
    run.add_argument(
        "--max-task-failure-rate",
        type=_rate,
        default=0.0,
        metavar="RATE",
        help="fail the run above this task failure rate (default: 0.0)",
    )
    run.add_argument("--warnings-as-errors", action="store_true", help="exit 1 on a WARN verdict")
    run.add_argument(
        "--quiet", action="store_true", help="print only non-PASS findings and the verdict"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        run = load(args.results, format=args.format)
    except LoadError as exc:
        print(f"eval-preflight: error: {exc}", file=sys.stderr)
        return 2

    config = CheckConfig(
        min_coverage=args.min_coverage,
        max_evaluator_error_rate=args.max_evaluator_error_rate,
        max_task_failure_rate=args.max_task_failure_rate,
    )
    result = check(run, config)
    render(result, Console(soft_wrap=True), quiet=args.quiet)
    return result.exit_code(warnings_as_errors=args.warnings_as_errors)
