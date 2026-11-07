# /// script
# requires-python = ">=3.11"
# ///
"""Generate the promptfoo fixtures by running the real promptfoo CLI (pinned below).

Run with `make promptfoo-fixtures`. Needs Node.js; `npx` fetches the pinned promptfoo.
Each scenario writes a promptfoo config plus two deterministic custom providers (the
task under test and an LLM judge) to a temporary directory, runs
`promptfoo eval -c <config> -o <out>.json --no-cache --no-write`, and writes the export
to tests/fixtures/promptfoo/<scenario>.json.

Normalised so the files are reproducible and carry no machine paths: ids, timestamps,
latencies, host metadata, and stack-trace frames in error messages. Nothing else is
touched. Never hand-edit the output; change this script and rerun.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

PROMPTFOO = "promptfoo@0.125.1"
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "promptfoo"

# The task under test: echoes the question; raises when the case sets `fail`.
TASK_JS = """\
module.exports = class Task {
  id() { return 'echo-task'; }
  async callApi(prompt, context) {
    if (context.vars.fail) throw new Error('upstream timeout');
    return { output: `answer: ${context.vars.q}` };
  }
};
"""

# An LLM judge that approves every answer.
JUDGE_JS = """\
module.exports = class Judge {
  id() { return 'judge'; }
  async callApi() {
    return { output: JSON.stringify({ pass: true, score: 1, reason: 'polite' }) };
  }
};
"""

# An LLM judge whose quota runs out after the first case: only c1 gets a verdict.
FLAKY_JUDGE_JS = """\
module.exports = class FlakyJudge {
  id() { return 'flaky-judge'; }
  async callApi(prompt) {
    if (!prompt.includes('answer: c1')) return { error: 'judge quota exhausted' };
    return { output: JSON.stringify({ pass: true, score: 1, reason: 'polite' }) };
  }
};
"""


def config(
    name: str, judge: str, failing: tuple[str, ...] = (), extra: tuple[dict[str, Any], ...] = ()
) -> dict[str, Any]:
    tests = []
    for case in ("c1", "c2", "c3", "c4"):
        variables: dict[str, Any] = {"q": case}
        if case in failing:
            variables["fail"] = True
        tests.append({"description": case, "vars": variables})
    return {
        "description": name,
        "prompts": ["Q: {{q}}"],
        "providers": ["file://task.js"],
        "defaultTest": {
            "assert": [
                {"type": "contains", "value": "answer"},
                {"type": "javascript", "value": "output.length > 3", "metric": "nonempty"},
                {"type": "llm-rubric", "value": "is polite", "provider": f"file://{judge}"},
                *extra,
            ]
        },
        "tests": tests,
    }


# An assert-set: promptfoo writes a summary entry (no `assertion`) plus its flattened children.
ASSERT_SET = {
    "type": "assert-set",
    "assert": [
        {"type": "icontains", "value": "ANSWER"},
        {"type": "starts-with", "value": "answer"},
    ],
}

# scenario -> (config, --repeat)
SCENARIOS: dict[str, tuple[dict[str, Any], int]] = {
    # Every assertion passes on every case-run; repeats exercise repeatIndex.
    "clean_run": (config("clean_run", "judge.js", extra=(ASSERT_SET,)), 2),
    # The judge errors on c2-c4. promptfoo records each as a failed assertion
    # (pass false, score 0, metadata.graderError true).
    "judge_errors": (config("judge_errors", "flaky_judge.js"), 1),
    # The task raises on c3: failureReason 2 (ERROR), no grading result.
    "task_errors": (config("task_errors", "judge.js", failing=("c3",)), 1),
}

_VOLATILE = {
    "evalId",
    "id",
    "timestamp",
    "exportedAt",
    "evaluationCreatedAt",
    "latencyMs",
    "totalLatencyMs",
    "durationMs",
    "evaluationDurationMs",
    "nodeVersion",
    "platform",
    "arch",
}
_STACK_FRAME = re.compile(r"\n\s+at .*")


def normalise(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: ("<removed>" if key in _VOLATILE and value is not None else normalise(value))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [normalise(value) for value in node]
    if isinstance(node, str):
        return _STACK_FRAME.sub("", node)
    return node


def run_scenario(workdir: Path, scenario: str) -> dict[str, Any]:
    cfg, repeat = SCENARIOS[scenario]
    config_path = workdir / f"{scenario}.json"
    out_path = workdir / f"{scenario}.out.json"
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    env = {
        **os.environ,
        "PROMPTFOO_DISABLE_TELEMETRY": "1",
        "PROMPTFOO_DISABLE_UPDATE": "1",
        "PROMPTFOO_DISABLE_SHARING": "1",
    }
    command = ["npx", "--yes", PROMPTFOO, "eval", "-c", config_path.name, "-o", out_path.name]
    command += ["--no-cache", "--no-write", "--no-table", "--max-concurrency", "1"]
    command += ["--repeat", str(repeat)]
    # promptfoo exits non-zero when any test fails; the export is still written.
    subprocess.run(command, cwd=workdir, env=env, check=False, capture_output=True)
    if not out_path.exists():
        raise SystemExit(f"promptfoo wrote no export for {scenario}")
    document: dict[str, Any] = json.loads(out_path.read_text(encoding="utf-8"))
    return document


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "task.js").write_text(TASK_JS, encoding="utf-8")
        (workdir / "judge.js").write_text(JUDGE_JS, encoding="utf-8")
        (workdir / "flaky_judge.js").write_text(FLAKY_JUDGE_JS, encoding="utf-8")
        version = None
        for scenario in SCENARIOS:
            document = run_scenario(workdir, scenario)
            version = document["metadata"]["promptfooVersion"]
            path = OUT / f"{scenario}.json"
            text = json.dumps(normalise(document), indent=2) + "\n"
            for prefix in (str(workdir.resolve()), tmp):  # macOS: /private/var vs /var
                text = text.replace(prefix, "<tmp>")
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(OUT.parent.parent.parent)}")
    (OUT / "VERSION").write_text(f"promptfoo=={version}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
