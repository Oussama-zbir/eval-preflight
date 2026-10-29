"""The golden scenarios as real pydantic-evals datasets, from scripts/make_fixtures.py.

The in-memory tests run the same definitions that generated the JSON fixtures, so
both paths are checked against one source of truth. Needs pydantic-evals (dev group).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_fixtures.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("make_fixtures", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered first: dataclasses resolve string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


make_fixtures = _load()
SCENARIOS: list[str] = list(make_fixtures.SCENARIOS)


def run_scenario(name: str) -> Any:
    """The EvaluationReport of one scenario, produced by the real library."""
    return make_fixtures.run_scenario(name)
