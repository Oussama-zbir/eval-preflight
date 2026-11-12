# /// script
# requires-python = ">=3.11"
# ///
"""Probe what the promptfoo CLI reports on partial and failed scoring (docs/research-notes.md).

Run with `make research` (equivalently
`uv run --no-project scripts/research/promptfoo_probe.py`). Needs Node.js; `npx` fetches the
pinned promptfoo. No API key: the task and the judge are deterministic local providers.

Four cases `c1`..`c4`, one prompt, one provider. Each scenario differs only in its assertions,
the task, or the environment:

- `judge_errors`: an `llm-rubric` judge returns a provider error on c2-c4.
- `judge_errors_threshold_25`: same, with `PROMPTFOO_PASS_RATE_THRESHOLD=25`.
- `task_errors`: the task under test raises on c2-c4.
- `task_errors_threshold_25`: same, with `PROMPTFOO_PASS_RATE_THRESHOLD=25`.
- `assertion_throws`: a `javascript` assertion throws on c2-c4.
- `assertion_returns_undefined`: a `javascript` assertion returns `undefined` on c2-c4.
- `two_assertions_same_metric`: two `javascript` assertions share `metric: judge`; one
  scores 0.25 and the other 1 on every case.

Each scenario runs `promptfoo eval`, whose exit code is what a CI step sees, and the JSON export
is read back. Writes docs/research/promptfoo-<version>.json with stack frames and temporary
paths removed. Never hand-edit the output; change this script and rerun.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

VERSION = "0.125.1"
OUT = Path(__file__).resolve().parents[2] / "docs" / "research" / f"promptfoo-{VERSION}.json"
CASES = ("c1", "c2", "c3", "c4")

# Echoes the question; raises when the case sets `fail`.
TASK_JS = """\
module.exports = class Task {
  id() { return 'echo-task'; }
  async callApi(prompt, context) {
    if (context.vars.fail) throw new Error('upstream timeout');
    return { output: `answer: ${context.vars.q}` };
  }
};
"""

# A judge whose quota runs out after the first case: only c1 gets a verdict.
FLAKY_JUDGE_JS = """\
module.exports = class FlakyJudge {
  id() { return 'flaky-judge'; }
  async callApi(prompt) {
    if (!prompt.includes('answer: c1')) return { error: 'judge quota exhausted' };
    return { output: JSON.stringify({ pass: true, score: 1, reason: 'polite' }) };
  }
};
"""

CONTAINS = {"type": "contains", "value": "answer"}
FLAKY_JUDGE = {"type": "llm-rubric", "value": "is polite", "provider": "file://flaky_judge.js"}
THROWS = {
    "type": "javascript",
    # A multi-line value is run as a function body; a one-liner as an expression.
    "value": "if (context.vars.q !== 'c1') throw new Error('grader bug');\nreturn true;",
}
UNDEFINED = {
    "type": "javascript",
    "value": "if (context.vars.q === 'c1') return true;\nreturn undefined;",
}
STRICT = {"type": "javascript", "value": "0.25", "metric": "judge"}
LENIENT = {"type": "javascript", "value": "1", "metric": "judge"}

THRESHOLD_25 = {"PROMPTFOO_PASS_RATE_THRESHOLD": "25"}

# scenario -> (assertions, cases on which the task raises, extra environment)
SCENARIOS: dict[str, tuple[list[dict[str, Any]], tuple[str, ...], dict[str, str]]] = {
    "judge_errors": ([CONTAINS, FLAKY_JUDGE], (), {}),
    "judge_errors_threshold_25": ([CONTAINS, FLAKY_JUDGE], (), THRESHOLD_25),
    "task_errors": ([CONTAINS], ("c2", "c3", "c4"), {}),
    "task_errors_threshold_25": ([CONTAINS], ("c2", "c3", "c4"), THRESHOLD_25),
    "assertion_throws": ([CONTAINS, THROWS], (), {}),
    "assertion_returns_undefined": ([CONTAINS, UNDEFINED], (), {}),
    "two_assertions_same_metric": ([STRICT, LENIENT], (), {}),
}

_STACK_FRAME = re.compile(r"\n\s+at .*")


def config(name: str, assertions: list[dict[str, Any]], failing: tuple[str, ...]) -> dict[str, Any]:
    tests = []
    for case in CASES:
        variables: dict[str, Any] = {"q": case}
        if case in failing:
            variables["fail"] = True
        tests.append({"description": case, "vars": variables})
    return {
        "description": name,
        "prompts": ["Q: {{q}}"],
        "providers": ["file://task.js"],
        "defaultTest": {"assert": assertions},
        "tests": tests,
    }


def _text(value: Any, workdir: Path) -> Any:
    if not isinstance(value, str):
        return value
    value = _STACK_FRAME.sub("", value)
    for prefix in (str(workdir.resolve()), str(workdir)):  # macOS: /private/var vs /var
        value = value.replace(prefix, "<tmp>")
    return value


def summarise(document: dict[str, Any], workdir: Path) -> dict[str, Any]:
    results = document["results"]
    rows = {}
    for row in results["results"]:
        grading = row.get("gradingResult") or {}
        rows[row["testCase"]["description"]] = {
            "success": row["success"],
            "score": row["score"],
            "failureReason": row.get("failureReason"),
            "error": _text(row.get("error"), workdir),
            "namedScores": row.get("namedScores"),
            "assertions": [
                {
                    "type": c.get("assertion", {}).get("type"),
                    "metric": c.get("assertion", {}).get("metric"),
                    "pass": c.get("pass"),
                    "score": c.get("score"),
                    "reason": _text(c.get("reason"), workdir),
                    "graderError": (c.get("metadata") or {}).get("graderError"),
                }
                for c in grading.get("componentResults") or []
            ],
        }
    stats = results["stats"]
    return {
        "stats": {k: stats[k] for k in ("successes", "failures", "errors")},
        "prompt_metrics": {
            k: v
            for k, v in results["prompts"][0]["metrics"].items()
            if k in ("score", "testPassCount", "testFailCount", "testErrorCount", "namedScores")
        },
        "rows": dict(sorted(rows.items())),
    }


def run(workdir: Path, name: str) -> dict[str, Any]:
    assertions, failing, extra_env = SCENARIOS[name]
    config_path = workdir / f"{name}.json"
    out_path = workdir / f"{name}.out.json"
    config_path.write_text(json.dumps(config(name, assertions, failing), indent=2))
    env = {
        **os.environ,
        "PROMPTFOO_DISABLE_TELEMETRY": "1",
        "PROMPTFOO_DISABLE_UPDATE": "1",
        "PROMPTFOO_DISABLE_SHARING": "1",
        **extra_env,
    }
    for key in ("PROMPTFOO_PASS_RATE_THRESHOLD", "PROMPTFOO_FAILED_TEST_EXIT_CODE"):
        if key not in extra_env:
            env.pop(key, None)
    flags = ["--no-cache", "--no-write", "--no-table", "--max-concurrency", "1"]
    command = ["npx", "--yes", f"promptfoo@{VERSION}", "eval", "-c", config_path.name]
    command += ["-o", out_path.name, *flags]
    proc = subprocess.run(command, cwd=workdir, env=env, check=False, capture_output=True)
    if not out_path.exists():
        raise SystemExit(f"promptfoo wrote no export for {name}:\n{proc.stderr.decode()}")
    document = json.loads(out_path.read_text())
    if document["metadata"]["promptfooVersion"] != VERSION:
        raise SystemExit(f"expected promptfoo {VERSION}, got {document['metadata']}")
    return {
        "command": ["promptfoo", "eval", "-c", config_path.name, *flags],
        "env": extra_env,
        "config": {"assert": assertions, "task_raises_on": list(failing)},
        "exit_code": proc.returncode,
        **summarise(document, workdir),
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "task.js").write_text(TASK_JS)
        (workdir / "flaky_judge.js").write_text(FLAKY_JUDGE_JS)
        report = {
            "framework": "promptfoo",
            "version": VERSION,
            "generated_by": "scripts/research/promptfoo_probe.py",
            "scenarios": {name: run(workdir, name) for name in SCENARIOS},
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
