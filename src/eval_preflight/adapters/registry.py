"""Pick an adapter for an input file and load it into an EvalRun."""

from __future__ import annotations

import json
from pathlib import Path

from eval_preflight.adapters import LoadError, loads_json
from eval_preflight.adapters.generic import looks_generic, parse_generic
from eval_preflight.adapters.promptfoo import looks_promptfoo, parse_promptfoo
from eval_preflight.adapters.pydantic_evals import looks_pydantic_evals, parse_pydantic_evals
from eval_preflight.model import EvalRun

PARSERS = {
    "generic": parse_generic,
    "pydantic-evals": parse_pydantic_evals,
    "promptfoo": parse_promptfoo,
}
FORMATS = ("auto", *PARSERS)


def _first_json_value(text: str) -> object:
    """The whole text as JSON, else its first non-blank line (JSONL)."""
    try:
        return loads_json(text)
    except json.JSONDecodeError:
        pass
    first = next(line for line in text.splitlines() if line.strip())
    try:
        return loads_json(first)
    except json.JSONDecodeError as exc:
        raise LoadError(f"input is not valid JSON or JSONL ({exc.msg})") from exc


def detect(text: str) -> str:
    document = _first_json_value(text)
    if looks_generic(document):
        return "generic"
    if looks_pydantic_evals(document):
        return "pydantic-evals"
    if looks_promptfoo(document):
        return "promptfoo"
    raise LoadError("could not detect the input format; pass --format explicitly")


def load(path: str | Path, format: str = "auto") -> EvalRun:
    """Load an eval results file. format is one of FORMATS; "auto" detects it."""
    if format not in FORMATS:
        raise LoadError(f"unknown format {format!r}; expected one of {', '.join(FORMATS)}")
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LoadError(f"cannot read {path}: {exc}") from exc
    if not text.strip():
        raise LoadError("no case results in input")
    if format == "auto":
        format = detect(text)
    return PARSERS[format](text, default_name=path.stem)
