# /// script
# requires-python = ">=3.11"
# dependencies = ["pydantic-evals==2.61.0"]
# ///
"""Generate the pydantic-evals golden fixtures (SPEC.md §9) by running the real library.

Run with `make fixtures` (equivalently `uv run --no-project scripts/make_fixtures.py`).
uv installs the pinned pydantic-evals in an isolated environment; the project does
not depend on it.

Each scenario runs a Dataset with deterministic evaluators and writes
`TypeAdapter(EvaluationReport).dump_json(report, by_alias=True)` to
tests/fixtures/pydantic_evals/<scenario>.json. Two fields are normalised so the
files are reproducible and carry no machine paths: `error_stacktrace` (absolute
site-packages paths) and the wall-clock `task_duration` / `total_duration`.
Nothing else is touched. Never hand-edit the output; change this script and rerun.
"""

from __future__ import annotations

import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext
from pydantic_evals.reporting import EvaluationReport

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "pydantic_evals"
STACKTRACE = "<removed by scripts/make_fixtures.py>"


async def echo(inputs: str) -> str:
    return inputs


# Scenario A: partial coverage (pydantic/pydantic-ai#7928).
@dataclass
class FlakyScore(Evaluator[str, str, Any]):
    def evaluate(self, ctx: EvaluatorContext[str, str, Any]) -> float:
        if ctx.inputs != "c1":
            raise RuntimeError("judge quota exhausted")
        return 1.0


@dataclass
class AlwaysScores(Evaluator[str, str, Any]):
    def evaluate(self, ctx: EvaluatorContext[str, str, Any]) -> float:
        return 0.5


# Scenario B: name shift (pydantic/pydantic-ai#10636).
@dataclass
class Judge(Evaluator[str, str, Any]):
    rubric: str

    def evaluate(self, ctx: EvaluatorContext[str, str, Any]) -> float:
        if self.rubric == "lenient":
            return 1.0
        if ctx.inputs != "c1":
            raise RuntimeError("judge quota exhausted")
        return 0.0


# Scenario C (repeat divergence) is not generated yet: as specified it cannot be
# expressed without tripping checks 2 or 4 (see BACKLOG.md).


# Scenario D: clean run, varying values.
@dataclass
class Relevance(Evaluator[str, str, Any]):
    def evaluate(self, ctx: EvaluatorContext[str, str, Any]) -> float:
        return {"c1": 0.9, "c2": 0.6, "c3": 0.75, "c4": 0.3}[ctx.inputs]


@dataclass
class NonEmpty(Evaluator[str, str, Any]):
    def evaluate(self, ctx: EvaluatorContext[str, str, Any]) -> bool:
        return ctx.inputs != "c4"


def cases(*names: str) -> list[Case[str, str, Any]]:
    return [Case(name=name, inputs=name) for name in names]


SCENARIOS: dict[str, tuple[Dataset[str, str, Any], int]] = {
    "partial_coverage": (
        Dataset(
            name="partial_coverage",
            cases=cases("c1", "c2", "c3", "c4"),
            evaluators=[FlakyScore(), AlwaysScores()],
        ),
        1,
    ),
    "name_shift": (
        Dataset(
            name="name_shift",
            cases=cases("c1", "c2", "c3", "c4"),
            evaluators=[Judge(rubric="strict"), Judge(rubric="lenient")],
        ),
        1,
    ),
    "clean_run": (
        Dataset(
            name="clean_run",
            cases=cases("c1", "c2", "c3", "c4"),
            evaluators=[Relevance(), NonEmpty()],
        ),
        1,
    ),
}


def normalise(node: Any) -> Any:
    if isinstance(node, dict):
        out = {key: normalise(value) for key, value in node.items()}
        if "error_stacktrace" in out:
            out["error_stacktrace"] = STACKTRACE
        for key in ("task_duration", "total_duration"):
            if key in out:
                out[key] = 0.0
        return out
    if isinstance(node, list):
        return [normalise(value) for value in node]
    return node


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    adapter = TypeAdapter(EvaluationReport)
    for scenario, (dataset, repeat) in SCENARIOS.items():
        report = dataset.evaluate_sync(echo, progress=False, repeat=repeat, max_concurrency=1)
        document = normalise(json.loads(adapter.dump_json(report, by_alias=True)))
        path = OUT / f"{scenario}.json"
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(OUT.parent.parent.parent)}")
    version = importlib.metadata.version("pydantic-evals")
    (OUT / "VERSION").write_text(f"pydantic-evals=={version}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
