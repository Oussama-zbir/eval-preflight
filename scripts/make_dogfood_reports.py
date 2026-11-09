# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pydantic-evals==2.66.0",
#   "pydantic-ai-slim[openai]==2.66.0",
#   "opentelemetry-sdk>=1.30",
# ]
# ///
"""Run two public pydantic-evals examples and save their reports for dogfooding (SPEC.md §11 M5).

Run with `make dogfood` (equivalently `uv run --no-project scripts/make_dogfood_reports.py`).

1. `title_case`: the "Simple Validation" example from the pydantic-evals docs
   (https://pydantic.dev/docs/ai/evals/examples/simple-validation/), dataset and task
   copied verbatim. Deterministic, no model involved.
2. `time_range`: `pydantic_ai_examples.evals` from the `pydantic-ai-examples` 2.66.0 wheel
   on PyPI (downloaded and checked against its published sha256; the wheel is imported
   directly so its unrelated dependencies are not installed). The example's own agent,
   tool, custom evaluators and `time_range_v2.yaml` dataset run as in
   `example_03_unit_testing.py`. The one substitution: no API key is used, so the agent's
   model and the LLMJudge model are pydantic-ai `FunctionModel`s. The agent model calls
   the example's `get_current_time` tool and then answers each case with its own
   `expected_output` (a perfect model); the judge passes everything. Findings on this
   report therefore come from the dataset and evaluator design, not from model quality.

Reports are written like scripts/make_fixtures.py writes fixtures, with the same
normalisation (stack traces, durations). Never hand-edit the output; change this script
and rerun.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from types import NoneType
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from pydantic import TypeAdapter
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Contains, EqualsExpected, IsInstance, MaxDuration
from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model
from pydantic_evals.reporting import EvaluationReport

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "dogfood"
STACKTRACE = "<removed by scripts/make_dogfood_reports.py>"

EXAMPLES_WHEEL = (
    "https://files.pythonhosted.org/packages/6f/f7/"
    "6d12f82cb42bea6faf99e2c335b941d53b3c0e6f5669a525673e4e2f0308/"
    "pydantic_ai_examples-2.66.0-py3-none-any.whl"
)
EXAMPLES_SHA256 = "fbc2c98a103281b786ca1802b26e69ca557f81d838c35a87a2edf3258615d533"
TIME_RANGE_DATASET = "pydantic_ai_examples/evals/datasets/time_range_v2.yaml"


# --- Example 1: docs "Simple Validation" (verbatim) ---------------------------------


def to_title_case(text: str) -> str:
    """Convert text to title case."""
    return text.title()


def title_case_dataset() -> Dataset[str, str, Any]:
    return Dataset(
        name="title_case_validation",
        cases=[
            Case(name="basic_lowercase", inputs="hello world", expected_output="Hello World"),
            Case(name="basic_uppercase", inputs="HELLO WORLD", expected_output="Hello World"),
            Case(name="mixed_case", inputs="HeLLo WoRLd", expected_output="Hello World"),
            Case(name="empty_string", inputs="", expected_output=""),
            Case(name="single_word", inputs="hello", expected_output="Hello"),
            Case(name="with_punctuation", inputs="hello, world!", expected_output="Hello, World!"),
            Case(name="with_numbers", inputs="hello 123 world", expected_output="Hello 123 World"),
            Case(
                name="apostrophes",
                inputs="don't stop believin'",
                expected_output="Don'T Stop Believin'",
            ),
        ],
        evaluators=[
            IsInstance(type_name="str"),
            EqualsExpected(),
            Contains(value="H", evaluation_name="has_capitals"),
            MaxDuration(seconds=0.001),
        ],
    )


def run_title_case() -> EvaluationReport[Any, Any, Any]:
    return title_case_dataset().evaluate_sync(to_title_case, progress=False, max_concurrency=1)


# --- Example 2: pydantic_ai_examples.evals time-range agent --------------------------


def fetch_examples_wheel(directory: Path) -> Path:
    path = directory / EXAMPLES_WHEEL.rsplit("/", 1)[1]
    with urllib.request.urlopen(EXAMPLES_WHEEL) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXAMPLES_SHA256:
        raise SystemExit(f"pydantic-ai-examples wheel sha256 mismatch: {digest}")
    path.write_bytes(data)
    return path


def run_time_range(wheel: Path) -> EvaluationReport[Any, Any, Any]:
    # The example's AgentCalledTool evaluator reads the span tree, which needs a tracer
    # provider (the example calls logfire.configure for this).
    trace.set_tracer_provider(TracerProvider())
    # agent.py builds an OpenAI provider at import time, which requires a key. The model is
    # overridden below, so a placeholder (never a real key) guarantees no request is sent.
    os.environ["OPENAI_API_KEY"] = "unused-placeholder"
    sys.path.insert(0, str(wheel))
    from pydantic_ai_examples.evals import infer_time_range
    from pydantic_ai_examples.evals.agent import time_range_agent
    from pydantic_ai_examples.evals.custom_evaluators import CUSTOM_EVALUATOR_TYPES
    from pydantic_ai_examples.evals.models import TimeRangeInputs, TimeRangeResponse

    with zipfile.ZipFile(wheel) as archive:
        text = archive.read(TIME_RANGE_DATASET).decode("utf-8")
    dataset = Dataset[TimeRangeInputs, TimeRangeResponse, NoneType].from_text(
        # from_file names the dataset after the file stem; from_text needs it explicitly.
        text,
        custom_evaluator_types=CUSTOM_EVALUATOR_TYPES,
        default_name="time_range_v2",
    )
    expected = {case.inputs["prompt"]: case.expected_output for case in dataset.cases}

    def perfect_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        parts = [
            part
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        ]
        if not any(isinstance(part, ToolReturnPart) for part in parts):
            return ModelResponse(parts=[ToolCallPart(tool_name="get_current_time", args={})])
        prompt = next(part.content for part in parts if isinstance(part, UserPromptPart))
        answer = expected[str(prompt)]
        assert answer is not None
        kind = type(answer).__name__
        (tool,) = [tool for tool in info.output_tools if tool.name.endswith(kind)]
        return ModelResponse(
            parts=[ToolCallPart(tool_name=tool.name, args=answer.model_dump(mode="json"))]
        )

    def passing_judge(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        (tool,) = info.output_tools
        args = {"reason": "stub judge", "pass": True, "score": 1.0}
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])

    set_default_judge_model(FunctionModel(passing_judge))
    with time_range_agent.override(model=FunctionModel(perfect_model)):
        return dataset.evaluate_sync(infer_time_range, progress=False, max_concurrency=1)


# --- Output ---------------------------------------------------------------------------


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


def write(name: str, report: EvaluationReport[Any, Any, Any]) -> None:
    document = normalise(json.loads(TypeAdapter(EvaluationReport).dump_json(report, by_alias=True)))
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(OUT.parent.parent.parent)}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write("title_case", run_title_case())
    with tempfile.TemporaryDirectory() as directory:
        write("time_range", run_time_range(fetch_examples_wheel(Path(directory))))
    versions = [
        f"{name}=={importlib.metadata.version(name)}"
        for name in ("pydantic-evals", "pydantic-ai-slim")
    ]
    versions.append("pydantic-ai-examples==2.66.0 (wheel, sha256 pinned)")
    (OUT / "VERSION").write_text("\n".join(versions) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
