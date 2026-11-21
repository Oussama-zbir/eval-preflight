# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "arize-phoenix==22.0.0",
#   "arize-phoenix-client==3.7.0",
#   "arize-phoenix-evals==3.10.0",
#   "pandas==3.1.1",
# ]
# ///
"""Probe how Arize Phoenix reports partial and failed scoring (docs/research-notes.md).

Run with `make research` (equivalently `uv run --no-project scripts/research/phoenix_probe.py`).
No account, no API key and nothing leaves the machine: the probe starts a real Phoenix server on
loopback with a throwaway SQLite database, `PHOENIX_ALLOW_EXTERNAL_RESOURCES=false` and telemetry
off, and every task and evaluator is deterministic.

Two Phoenix APIs score a set of cases, and the probe covers both:

- Experiments (`phoenix.client`, `Client().experiments.run_experiment`): the task and evaluators
  run in the client, results are stored by the server, and the server computes the per-evaluator
  summary the Phoenix UI shows (GraphQL `Experiment.annotationSummaries`). Even a `dry_run`
  experiment fetches its dataset from a server, so a server is needed either way.
- `phoenix.evals.evaluate_dataframe`: runs evaluators over a DataFrame locally, no server.

Every scenario uses four cases `c1`..`c4` (input = reference = case id, the task echoes the input)
and an exact-match evaluator `judge` that scores 1.0 on c1:

Experiments:
- `experiment_evaluator_raises`: `judge` raises on c2-c4.
- `experiment_evaluator_returns_none`: `judge` returns `None` on c2-c4.
- `experiment_evaluator_returns_score_none`: `judge` returns `{"score": None}` on c2-c4.
- `experiment_two_evaluators_same_name`: `create_evaluator(name="judge")` on two functions,
  `strict` (0.0 on every case) then `lenient` (1.0 on every case).
- `experiment_task_raises`: the task raises on c2-c4.

`evaluate_dataframe`:
- `dataframe_evaluator_raises`: `judge` raises on c2-c4, defaults (`exit_on_error` and
  `max_retries` not passed).
- `dataframe_evaluator_raises_continue`: same, `exit_on_error=False, max_retries=0`.
- `dataframe_evaluator_returns_none`: `judge` returns `None` on c2-c4, defaults.
- `dataframe_evaluator_returns_score_none`: `judge` returns `{"score": None}` on c2-c4, defaults.
- `dataframe_two_evaluators_same_name`: as in experiments, defaults.

Each scenario runs in its own process. For experiments the probe records whether
`run_experiment` raised, the summary line it printed, how many evaluator errors it printed, each
evaluation run (case, name, score, error) and the server's run count, error rate and annotation
summaries. For `evaluate_dataframe` it records whether the call raised, each case's
`*_execution_details` status and exception count and each `*_score` column, the pandas mean of the
scores in each column, and how many retry and give-up lines Phoenix printed.

Writes docs/research/phoenix-<arize-phoenix version>.json. Never hand-edit the output; change this
script and rerun.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path
from typing import Any

VERSIONS = {
    "arize-phoenix": "22.0.0",
    "arize-phoenix-client": "3.7.0",
    "arize-phoenix-evals": "3.10.0",
}
OUT = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / f"phoenix-{VERSIONS['arize-phoenix']}.json"
)

EXPERIMENT_FILE = """\
import contextlib
import io
import json
import os
import sys
import urllib.request

from phoenix.client import Client
from phoenix.client.experiments import create_evaluator

SCENARIO = os.environ["PROBE_SCENARIO"]
BASE_URL = os.environ["PHOENIX_COLLECTOR_ENDPOINT"]
FAILING = {"c2", "c3", "c4"}


def task(input):
    if SCENARIO == "experiment_task_raises" and input["case"] in FAILING:
        raise RuntimeError("model timeout")
    return {"answer": input["case"]}


def judge(input, output, expected):
    if input["case"] in FAILING:
        if SCENARIO == "experiment_evaluator_raises":
            raise RuntimeError("judge quota exhausted")
        if SCENARIO == "experiment_evaluator_returns_none":
            return None
        if SCENARIO == "experiment_evaluator_returns_score_none":
            return {"score": None}
    return float(output is not None and output["answer"] == expected["answer"])


@create_evaluator(name="judge")
def strict(output):
    return 0.0


@create_evaluator(name="judge")
def lenient(output):
    return 1.0


EVALUATORS = {"experiment_two_evaluators_same_name": [strict, lenient]}

QUERY = '''
query ($id: ID!) {
  node(id: $id) {
    ... on Experiment {
      runCount
      expectedRunCount
      errorRate
      annotationSummaries {
        annotationName meanScore minScore maxScore count errorCount scoreCount labelCount
      }
    }
  }
}
'''


def graphql(experiment_id):
    body = json.dumps({"query": QUERY, "variables": {"id": experiment_id}}).encode()
    request = urllib.request.Request(
        f"{BASE_URL}/graphql", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)["data"]["node"]


client = Client(base_url=BASE_URL)
dataset = client.datasets.create_dataset(
    name=SCENARIO,
    inputs=[{"case": f"c{i}"} for i in range(1, 5)],
    outputs=[{"answer": f"c{i}"} for i in range(1, 5)],
)
case_by_example = {ex["id"]: ex["input"]["case"] for ex in dataset.examples}

stdout, stderr = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
    try:
        result = client.experiments.run_experiment(
            dataset=dataset,
            task=task,
            evaluators=EVALUATORS.get(SCENARIO, [judge]),
        )
        raised = None
    except Exception as e:
        result, raised = None, f"{type(e).__name__}: {e}"

printed = stdout.getvalue() + stderr.getvalue()
report = {
    "raised": raised,
    "summary_line": next(
        (line for line in printed.splitlines() if line.startswith("Experiment completed")), None
    ),
    "evaluator_errors_printed": printed.count("evaluator failed for example"),
    "task_errors_printed": printed.count("task failed for example"),
}
if result is not None:
    case_by_run = {
        run["id"]: case_by_example[run["dataset_example_id"]] for run in result["task_runs"]
    }
    report["task_runs"] = sorted(
        (
            {"case": case_by_run[run["id"]], "error": run.get("error")}
            for run in result["task_runs"]
        ),
        key=lambda r: r["case"],
    )
    report["evaluation_runs"] = sorted(
        (
            {
                "case": case_by_run[ev.experiment_run_id],
                "name": ev.name,
                "score": (ev.result or {}).get("score"),
                "error": ev.error,
            }
            for ev in result["evaluation_runs"]
        ),
        key=lambda r: (r["case"], r["name"], r["score"] is None, r["score"]),
    )
    report["server"] = graphql(result["experiment_id"])
with open(sys.argv[1], "w") as f:
    json.dump(report, f)
"""

DATAFRAME_FILE = """\
import contextlib
import io
import json
import math
import os
import sys

import pandas as pd
from phoenix.evals import create_evaluator, evaluate_dataframe

SCENARIO = os.environ["PROBE_SCENARIO"]
FAILING = {"c2", "c3", "c4"}


@create_evaluator(name="judge")
def judge(case, answer, reference):
    if case in FAILING:
        if SCENARIO.startswith("dataframe_evaluator_raises"):
            raise RuntimeError("judge quota exhausted")
        if SCENARIO == "dataframe_evaluator_returns_none":
            return None
        if SCENARIO == "dataframe_evaluator_returns_score_none":
            return {"score": None}
    return float(answer == reference)


@create_evaluator(name="judge")
def strict(case):
    return 0.0


@create_evaluator(name="judge")
def lenient(case):
    return 1.0


EVALUATORS = {"dataframe_two_evaluators_same_name": [strict, lenient]}
KWARGS = {"dataframe_evaluator_raises_continue": {"exit_on_error": False, "max_retries": 0}}

df = pd.DataFrame(
    {
        "case": [f"c{i}" for i in range(1, 5)],
        "answer": [f"c{i}" for i in range(1, 5)],
        "reference": [f"c{i}" for i in range(1, 5)],
    }
)
out = io.StringIO()
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
    try:
        result = evaluate_dataframe(
            dataframe=df,
            evaluators=EVALUATORS.get(SCENARIO, [judge]),
            hide_tqdm_bar=True,
            **KWARGS.get(SCENARIO, {}),
        )
        raised = None
    except Exception as e:
        result, raised = None, f"{type(e).__name__}: {e}"

printed = out.getvalue()
report = {
    "raised": raised,
    "retry_lines_printed": printed.count("Retrying..."),
    "gave_up_lines_printed": printed.count("Retries exhausted"),
}
if result is not None:
    detail_cols = sorted(c for c in result.columns if c.endswith("_execution_details"))
    score_cols = sorted(c for c in result.columns if c.endswith("_score"))
    report["rows"] = [
        {
            "case": row["case"],
            **{
                c: {"status": row[c]["status"], "exceptions": len(row[c]["exceptions"])}
                for c in detail_cols
            },
            **{c: None if row[c] is None else row[c].get("score") for c in score_cols},
        }
        for row in result.to_dict("records")
    ]

    def column(name):
        scores = result[name].map(lambda s: None if s is None else s.get("score")).astype(float)
        mean = scores.mean()
        return {"mean": None if math.isnan(mean) else mean, "count": int(scores.count())}

    report["score_columns"] = {c: column(c) for c in score_cols}
with open(sys.argv[1], "w") as f:
    json.dump(report, f)
"""

EXPERIMENT_SCENARIOS = [
    "experiment_evaluator_raises",
    "experiment_evaluator_returns_none",
    "experiment_evaluator_returns_score_none",
    "experiment_two_evaluators_same_name",
    "experiment_task_raises",
]
DATAFRAME_SCENARIOS = [
    "dataframe_evaluator_raises",
    "dataframe_evaluator_raises_continue",
    "dataframe_evaluator_returns_none",
    "dataframe_evaluator_returns_score_none",
    "dataframe_two_evaluators_same_name",
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def _env(extra: dict[str, str]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PHOENIX_", "OTEL_"))}
    return {
        **env,
        "PHOENIX_ALLOW_EXTERNAL_RESOURCES": "false",
        "PHOENIX_TELEMETRY_ENABLED": "false",
        **extra,
    }


def _wait_healthy(base_url: str, server: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise SystemExit(f"phoenix server exited with {server.returncode}")
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise SystemExit("phoenix server did not become healthy within 120 s")


def run(workdir: Path, probe_file: Path, scenario: str, env: dict[str, str]) -> dict[str, Any]:
    out = workdir / f"{scenario}.json"
    proc = subprocess.run(
        [sys.executable, "-I", str(probe_file), str(out)],
        cwd=workdir,
        env={**env, "PROBE_SCENARIO": scenario},
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0 or not out.exists():
        raise SystemExit(f"{scenario}: probe process failed\n{proc.stdout}\n{proc.stderr}")
    result: dict[str, Any] = json.loads(out.read_text())
    return result


def main() -> None:
    for package, expected in VERSIONS.items():
        installed = version(package)
        if installed != expected:
            raise SystemExit(f"expected {package} {expected}, found {installed}")
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "phoenix").mkdir()
        experiment_file = workdir / "probe_experiment.py"
        experiment_file.write_text(EXPERIMENT_FILE)
        dataframe_file = workdir / "probe_dataframe.py"
        dataframe_file.write_text(DATAFRAME_FILE)

        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        server_env = _env(
            {
                "PHOENIX_WORKING_DIR": str(workdir / "phoenix"),
                "PHOENIX_HOST": "127.0.0.1",
                "PHOENIX_PORT": str(port),
                "PHOENIX_GRPC_PORT": str(_free_port()),
            }
        )
        with (workdir / "server.log").open("wb") as log:
            server = subprocess.Popen(
                [str(Path(sys.executable).parent / "phoenix"), "serve"],
                cwd=workdir,
                env=server_env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                _wait_healthy(base_url, server)
                client_env = _env({"PHOENIX_COLLECTOR_ENDPOINT": base_url})
                scenarios = {
                    name: run(workdir, experiment_file, name, client_env)
                    for name in EXPERIMENT_SCENARIOS
                }
            finally:
                server.terminate()
                server.wait(timeout=30)
        scenarios |= {
            name: run(workdir, dataframe_file, name, _env({})) for name in DATAFRAME_SCENARIOS
        }
    report = {
        "framework": "phoenix",
        "versions": VERSIONS,
        "generated_by": "scripts/research/phoenix_probe.py",
        "calls": {
            "experiment": "Client().experiments.run_experiment(dataset=..., task=..., "
            "evaluators=[...]) against a local `phoenix serve` (SQLite)",
            "dataframe": "phoenix.evals.evaluate_dataframe(dataframe=..., evaluators=[...], "
            "hide_tqdm_bar=True)",
        },
        "scenarios": scenarios,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}")


if __name__ == "__main__":
    main()
