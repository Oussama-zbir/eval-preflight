# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "logfire==6.0.0",
#   "pydantic-evals==2.71.0",
# ]
# ///
"""Probe what Logfire receives for partial and failed pydantic-evals scoring (research-notes.md).

Run with `make research` (equivalently `uv run --no-project scripts/research/logfire_probe.py`).
No account, no token and nothing leaves the machine: `logfire.configure(send_to_logfire=False)`
plus `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` pointed at an OTLP/HTTP receiver this script runs on
loopback. That endpoint makes Logfire add a standard OTLP exporter to the same span pipeline that
feeds its own exporter, so the receiver gets the spans a Logfire project (or any OTLP backend)
would get, as protobuf on the wire. The Logfire UI itself is not probed.

Here Logfire is the destination, not the runner: it receives the spans pydantic-evals emits
(`evaluate {name}` with `logfire.experiment.metadata`, one `case: {case_name}` child per case, and
one `evaluator: {evaluator_name}` child per evaluator call). The probe records what those spans
carry next to the in-process `EvaluationReport` from the same run.

Every scenario uses four cases `c1`..`c4` (inputs = case name, the task echoes the input) and an
evaluator `Judge` that scores 1.0 on c1:

- `evaluator_raises`: `Judge` raises on c2-c4.
- `evaluator_returns_empty`: `Judge` returns `{}` (no result) on c2-c4.
- `evaluator_on_c1_only`: `Judge` is attached to case c1 only (`Case(evaluators=...)`), none on
  the dataset.
- `two_evaluators_same_name`: two `Judge` instances, `strict` (0.0 on every case) then `lenient`
  (1.0 on every case).
- `same_name_first_raises`: as above, but `strict` scores 0.0 on c1 and raises on c2-c4
  (pydantic/pydantic-ai#10636).
- `task_raises`: the task raises on c2-c4.

Each scenario runs in its own process. Span ids, timestamps, durations and source locations are
not recorded, so two runs write byte-identical output.

Writes docs/research/logfire-<logfire version>.json. Never hand-edit the output; change this
script and rerun.
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span, Status

VERSIONS = {"logfire": "6.0.0", "pydantic-evals": "2.71.0"}
OUT = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / f"logfire-{VERSIONS['logfire']}.json"
)

SCENARIOS = [
    "evaluator_raises",
    "evaluator_returns_empty",
    "evaluator_on_c1_only",
    "two_evaluators_same_name",
    "same_name_first_raises",
    "task_raises",
]

PROBE_FILE = """\
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import logfire
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

SCENARIO = os.environ["PROBE_SCENARIO"]
FAILING = {"c2", "c3", "c4"}

logfire.configure(
    send_to_logfire=False, console=False, metrics=False, service_name="logfire-probe"
)


@dataclass
class Judge(Evaluator[str, str, Any]):
    rubric: str = "exact"

    def evaluate(self, ctx: EvaluatorContext[str, str, Any]) -> Any:
        if self.rubric == "strict":
            if SCENARIO == "same_name_first_raises" and ctx.inputs in FAILING:
                raise RuntimeError("judge quota exhausted")
            return 0.0
        if self.rubric == "lenient":
            return 1.0
        if ctx.inputs in FAILING:
            if SCENARIO == "evaluator_raises":
                raise RuntimeError("judge quota exhausted")
            if SCENARIO == "evaluator_returns_empty":
                return {}
        return float(ctx.output == ctx.inputs)


async def task(inputs: str) -> str:
    if SCENARIO == "task_raises" and inputs in FAILING:
        raise RuntimeError("model timeout")
    return inputs


if SCENARIO == "evaluator_on_c1_only":
    cases = [Case(name="c1", inputs="c1", evaluators=(Judge(),))]
    cases += [Case(name=f"c{i}", inputs=f"c{i}") for i in range(2, 5)]
    evaluators = []
else:
    cases = [Case(name=f"c{i}", inputs=f"c{i}") for i in range(1, 5)]
    if SCENARIO in ("two_evaluators_same_name", "same_name_first_raises"):
        evaluators = [Judge(rubric="strict"), Judge(rubric="lenient")]
    else:
        evaluators = [Judge()]

dataset = Dataset(name="probe", cases=cases, evaluators=evaluators)
report = dataset.evaluate_sync(task, name=SCENARIO, progress=False)
logfire.shutdown()

averages = report.averages()
result = {
    "cases": {
        case.name: {
            "scores": {k: v.value for k, v in case.scores.items()},
            "evaluator_failures": [f"{f.name}: {f.error_message}" for f in case.evaluator_failures],
        }
        for case in sorted(report.cases, key=lambda c: c.name)
    },
    "failures": {f.name: f.error_message for f in sorted(report.failures, key=lambda f: f.name)},
    "averages_scores": None if averages is None else averages.scores,
}
with open(sys.argv[1], "w") as f:
    json.dump(result, f)
"""

# Span attributes pydantic-evals sets as JSON strings.
JSON_ATTRIBUTES = {
    "scores",
    "assertions",
    "labels",
    "logfire.experiment.metadata",
    "logfire.experiment.report_evaluator_failures",
}

# Spans received by the OTLP receiver for the scenario being run.
SPANS: list[Span] = []


class Receiver(BaseHTTPRequestHandler):
    """Minimal OTLP/HTTP protobuf trace receiver: keeps every span it is sent."""

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        request = ExportTraceServiceRequest.FromString(body)
        for resource_spans in request.resource_spans:
            for scope_spans in resource_spans.scope_spans:
                SPANS.extend(scope_spans.spans)
        payload = ExportTraceServiceResponse().SerializeToString()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        pass


def _value(value: AnyValue) -> Any:
    kind = value.WhichOneof("value")
    if kind == "array_value":
        return [_value(v) for v in value.array_value.values]
    return getattr(value, kind) if kind else None


def _attributes(span: Span) -> dict[str, Any]:
    attrs = {a.key: _value(a.value) for a in span.attributes}
    return {k: json.loads(v) if k in JSON_ATTRIBUTES else v for k, v in attrs.items()}


def _status(span: Span) -> str:
    return str(Status.StatusCode.Name(span.status.code))


def _exceptions(span: Span) -> list[str]:
    found = []
    for event in span.events:
        if event.name == "exception":
            attrs = {a.key: _value(a.value) for a in event.attributes}
            found.append(f"{attrs['exception.type']}: {attrs['exception.message']}")
    return found


def _results(attrs: dict[str, Any], key: str) -> dict[str, Any] | None:
    if key not in attrs:
        return None
    return {name: result["value"] for name, result in attrs[key].items()}


def _summarise(spans: list[Span]) -> dict[str, Any]:
    spans = [s for s in spans if _attributes(s).get("logfire.span_type") == "span"]
    (experiment,) = (s for s in spans if s.name == "evaluate {name}")
    children: dict[bytes, list[Span]] = {}
    for span in spans:
        children.setdefault(span.parent_span_id, []).append(span)

    exp_attrs = _attributes(experiment)
    metadata = exp_attrs["logfire.experiment.metadata"]
    averages = metadata.get("averages")
    cases = {}
    for case in children.get(experiment.span_id, []):
        if case.name != "case: {case_name}":
            continue
        attrs = _attributes(case)
        evaluators = [
            {
                "evaluator_name": _attributes(ev)["evaluator_name"],
                "status": _status(ev),
                "exceptions": _exceptions(ev),
            }
            for ev in children.get(case.span_id, [])
            if ev.name == "evaluator: {evaluator_name}"
        ]
        cases[attrs["case_name"]] = {
            "status": _status(case),
            "exceptions": _exceptions(case),
            "has_output_attribute": "output" in attrs,
            "scores": _results(attrs, "scores"),
            "assertions": _results(attrs, "assertions"),
            "labels": _results(attrs, "labels"),
            "evaluator_spans": sorted(evaluators, key=lambda e: json.dumps(e, sort_keys=True)),
        }
    return {
        "experiment_span": {
            "status": _status(experiment),
            "exceptions": _exceptions(experiment),
            "n_cases": exp_attrs.get("n_cases"),
            "assertion_pass_rate": exp_attrs.get("assertion_pass_rate"),
            "metadata_keys": sorted(metadata),
            "averages_scores": None if averages is None else averages["scores"],
            "averages_assertions": None if averages is None else averages["assertions"],
            "report_evaluator_failures": exp_attrs.get(
                "logfire.experiment.report_evaluator_failures"
            ),
        },
        "case_spans": dict(sorted(cases.items())),
    }


def _env(endpoint: str, scenario: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LOGFIRE_", "OTEL_"))}
    return {
        **env,
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": endpoint,
        "OTEL_METRICS_EXPORTER": "none",
        "OTEL_LOGS_EXPORTER": "none",
        "PROBE_SCENARIO": scenario,
    }


def run(workdir: Path, probe_file: Path, endpoint: str, scenario: str) -> dict[str, Any]:
    SPANS.clear()
    out = workdir / f"{scenario}.json"
    proc = subprocess.run(
        [sys.executable, "-I", str(probe_file), str(out)],
        cwd=workdir,
        env=_env(endpoint, scenario),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0 or not out.exists():
        raise SystemExit(f"{scenario}: probe process failed\n{proc.stdout}\n{proc.stderr}")
    return {
        "report": json.loads(out.read_text()),
        "exported_spans": _summarise(SPANS),
    }


def main() -> None:
    for package, expected in VERSIONS.items():
        installed = version(package)
        if installed != expected:
            raise SystemExit(f"expected {package} {expected}, found {installed}")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1/traces"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            probe_file = workdir / "probe.py"
            probe_file.write_text(PROBE_FILE)
            scenarios = {name: run(workdir, probe_file, endpoint, name) for name in SCENARIOS}
    finally:
        server.shutdown()
    report = {
        "framework": "logfire",
        "versions": VERSIONS,
        "generated_by": "scripts/research/logfire_probe.py",
        "call": "logfire.configure(send_to_logfire=False, console=False, metrics=False) with "
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT on loopback; Dataset(...).evaluate_sync(task, "
        "name=<scenario>, progress=False)",
        "scenarios": scenarios,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}")


if __name__ == "__main__":
    main()
