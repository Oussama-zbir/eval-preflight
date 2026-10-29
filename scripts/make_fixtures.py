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
from collections.abc import Awaitable, Callable
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


async def echo_empty_on_c2(inputs: str) -> str:
    """Scenario E's task: a regression that returns an empty answer for c2."""
    return "" if inputs == "c2" else inputs


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


# Scenario C: repeat divergence (SPEC §9 C as amended in §15). One evaluator returns a
# dict of named assertions: one passing on case a, three failing on case b.
@dataclass
class CaseChecks(Evaluator[str, str, Any]):
    def evaluate(self, ctx: EvaluatorContext[str, str, Any]) -> dict[str, bool]:
        if ctx.inputs == "a":
            return {"a_check": True}
        return {"b_check_1": False, "b_check_2": False, "b_check_3": False}


# Scenario D: clean run, varying values. Scenario E reuses the same evaluators, so their
# ids match the baseline; Relevance raises on an empty answer, which only E's task gives.
@dataclass
class Relevance(Evaluator[str, str, Any]):
    def evaluate(self, ctx: EvaluatorContext[str, str, Any]) -> float:
        if not ctx.output:
            raise ValueError("cannot judge an empty answer")
        return {"c1": 0.9, "c2": 0.6, "c3": 0.75, "c4": 0.3}[ctx.inputs]


@dataclass
class NonEmpty(Evaluator[str, str, Any]):
    def evaluate(self, ctx: EvaluatorContext[str, str, Any]) -> bool:
        return ctx.inputs != "c4"


def cases(*names: str) -> list[Case[str, str, Any]]:
    return [Case(name=name, inputs=name) for name in names]


Task = Callable[[str], Awaitable[str]]

# scenario -> (dataset, repeat, task)
SCENARIOS: dict[str, tuple[Dataset[str, str, Any], int, Task]] = {
    "partial_coverage": (
        Dataset(
            name="partial_coverage",
            cases=cases("c1", "c2", "c3", "c4"),
            evaluators=[FlakyScore(), AlwaysScores()],
        ),
        1,
        echo,
    ),
    "name_shift": (
        Dataset(
            name="name_shift",
            cases=cases("c1", "c2", "c3", "c4"),
            evaluators=[Judge(rubric="strict"), Judge(rubric="lenient")],
        ),
        1,
        echo,
    ),
    "repeat_divergence": (
        Dataset(
            name="repeat_divergence",
            cases=cases("a", "b"),
            evaluators=[CaseChecks()],
        ),
        2,
        echo,
    ),
    "clean_run": (
        Dataset(
            name="clean_run",
            cases=cases("c1", "c2", "c3", "c4"),
            evaluators=[Relevance(), NonEmpty()],
        ),
        1,
        echo,
    ),
    # Scenario E: the candidate compared against clean_run (the baseline): c4 removed,
    # Relevance errors on c2.
    "baseline_candidate": (
        Dataset(
            name="baseline_candidate",
            cases=cases("c1", "c2", "c3"),
            evaluators=[Relevance(), NonEmpty()],
        ),
        1,
        echo_empty_on_c2,
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


def run_scenario(scenario: str) -> EvaluationReport[str, str, Any]:
    """Run one scenario with the real library (also used by the in-memory tests)."""
    dataset, repeat, task = SCENARIOS[scenario]
    return dataset.evaluate_sync(task, progress=False, repeat=repeat, max_concurrency=1)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    adapter = TypeAdapter(EvaluationReport)
    for scenario in SCENARIOS:
        report = run_scenario(scenario)
        document = normalise(json.loads(adapter.dump_json(report, by_alias=True)))
        path = OUT / f"{scenario}.json"
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(OUT.parent.parent.parent)}")
    version = importlib.metadata.version("pydantic-evals")
    (OUT / "VERSION").write_text(f"pydantic-evals=={version}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
