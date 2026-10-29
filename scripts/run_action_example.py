"""Run the eval-preflight steps of examples/github-action.yml locally or in CI.

Executes, in order, every step whose `id` starts with "preflight", with the job's
`env`, RESULTS pointed at the given file, and the shell GitHub Actions uses for
`run` on Linux (`bash --noprofile --norc -eo pipefail`). The install and "Run
evals" steps are the user's and are skipped; `eval-preflight` comes from the
current environment, i.e. this checkout. Exits with the first failing step's code.

    uv run python scripts/run_action_example.py \
        --results tests/fixtures/pydantic_evals/clean_run.json
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "github-action.yml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--workdir", type=Path, default=Path.cwd())
    args = parser.parse_args()

    workflow = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    (job,) = workflow["jobs"].values()
    steps = [s for s in job["steps"] if str(s.get("id", "")).startswith("preflight")]
    if not steps:
        print(f"no step with an id starting with 'preflight' in {EXAMPLE}", file=sys.stderr)
        return 2

    env = os.environ | {k: str(v) for k, v in job.get("env", {}).items()}
    env["RESULTS"] = str(args.results.resolve())
    # The eval-preflight console script of the running interpreter's environment.
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env['PATH']}"

    for step in steps:
        print(f"::group::{step.get('name', step['id'])}", flush=True)
        shell = ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]]
        code = subprocess.run(shell, cwd=args.workdir, env=env, check=False).returncode
        print("::endgroup::", flush=True)
        if code != 0:
            print(f"step {step['id']!r} exited {code}", file=sys.stderr)
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
