# eval-preflight — build spec and working prompt

> How to use this file: create an empty GitHub repo named `eval-preflight`, drop this file in as `SPEC.md`,
> then start your coding session with: *"Read SPEC.md fully. Create CLAUDE.md with the content in section 12.
> Then start Milestone 1 and stop at its definition of done."* Each later session: *"Read SPEC.md, CLAUDE.md and
> BACKLOG.md, then continue with Milestone N."*

> **Naming status (25 October 2026):** `eval-preflight` is a working name. An exact-name GitHub
> repository search found no obvious match, but related names exist. PyPI availability has **not**
> been confirmed through the registry. Verify both before creating a release or promising an install command.

## 1. Mission

Build `eval-preflight`, a small open-source Python library + CLI that checks whether an LLM eval run is
**complete and aggregated correctly** before anyone trusts its headline numbers or gates a deploy on them.

It answers one question: *"Can these numbers be trusted as a description of this run?"*
It does **not** answer *"is model A better than model B?"* (that is statistics: significance, confidence
intervals, effect sizes). Tools like `evaltrust` and `limen-eval` do that. `eval-preflight` runs **before** them.

Positioning line for the README: *"A pre-flight check for eval results. It catches partial runs, failed
judges, mislabelled scores and inconsistent aggregation, so the number you gate on is the number your eval
actually produced."*

## 2. Why this exists (evidence; cite it in the docs)

These failure modes were found in real, widely used tools during October 2026:

- **Partial coverage inflates the score.** In pydantic-evals, an LLM judge that scores 1 case of 4 and raises
  on the rest produces an `Averages` row and `report.averages()` identical to a judge that scored all 4
  (pydantic/pydantic-ai#7928). A threshold check passes on evidence that does not exist.
- **Scores filed under the wrong evaluator.** In pydantic-evals, two evaluators with the same default name are
  disambiguated with `_2`, `_3` suffixes *per case*, counting only evaluators that succeeded. When the first one
  fails on a case, the second one's value is stored under the first one's name
  (pydantic/pydantic-ai#10636). `averages().scores == {'Judge': 0.75, 'Judge_2': 1.0}` where the real strict
  judge scored 0.0.
- **The headline number changes with `repeat`.** For a fully deterministic task with no errors
  (case `a`: 1 passing assertion; case `b`: 3 failing), pydantic-evals reports an assertion pass rate of 0.25
  with `repeat=1` and 0.5 with `repeat=2`, while the baseline-diff view of the *same* `repeat=2` report shows
  25%. Two estimators (pooled vs mean of per-case means) are used in different code paths.
- **Exploratory landscape scan (October 2026):** the original investigation reviewed pydantic-evals,
  Logfire, promptfoo, deepeval, ragas, Inspect AI, Braintrust, LangSmith and Phoenix. It suggested that
  missing evaluator coverage and evaluator errors are not consistently represented in the headline CI gate.
  This is research context, **not a verified claim about every current framework version**. Before public
  comparison claims, document the inspected versions, example exports, links, and the exact gate behavior
  in `docs/research-notes.md`. Do not publish the blanket claim that none of these products support such checks.
- **Adjacent tools:** `evaltrust` audits confidence in model comparisons, and `limen-eval` estimates the
  same-configuration noise floor from repeated runs. These are adjacent, not identical to a pre-flight
  completeness/attribution audit. Whether their particular adapters retain unscored observations must be
  independently verified before making a public claim. Also note existing GitHub projects named
  `Threadborne/eval-integrity` and `elanthus/preflight-eval-results`: both concern evaluation reliability
  but differ in product form or immediate problem statement.

## 3. User and job

A developer or ML engineer who runs LLM evals (locally or in CI) and uses the result to decide something:
merge a PR, ship a prompt change, pick a model. The job: *before I act on this score, tell me if the run was
complete, the judges worked, the labels are right, and the aggregate is reproducible from the raw results.*

User zero: us, on pydantic-evals runs. Second: promptfoo users (largest OSS community, stable JSON export).

## 4. Non-goals (do not build these; put ideas in BACKLOG.md)

- Running evals, calling models, or any network access at runtime.
- Statistical significance, confidence intervals, power, judge-vs-human agreement.
- Dashboards, hosting, a web UI, telemetry.
- Supporting every framework. MVP: a generic format + pydantic-evals; promptfoo is a stretch goal.
- Fixing the upstream bugs. We detect; upstream fixes are separate contributions.

## 5. Canonical data model (stable after 0.1.0)

Pydantic v2 models in `src/eval_preflight/model.py`:

```python
Kind = Literal["score", "assertion", "label"]

class EvaluatorRef(BaseModel):
    id: str            # stable identity, e.g. "Judge(rubric='strict')"; built from the framework's spec, NEVER from the display key
    display_name: str  # the name the framework reported, e.g. "Judge" or "Judge_2"
    kind: Kind

class Measurement(BaseModel):
    evaluator: EvaluatorRef
    value: float | bool | str | None   # None when the evaluator produced nothing for this case
    error: str | None = None           # set when the evaluator failed on this case

class CaseResult(BaseModel):
    case_id: str                       # stable across runs; for repeats, the original case name
    run_index: int = 0                 # 0-based repeat index
    task_error: str | None = None      # the task under test raised; no measurements expected
    measurements: list[Measurement] = []

class EvalRun(BaseModel):
    name: str
    source: str                        # "generic" | "pydantic-evals" | "promptfoo"
    source_version: str | None = None
    cases: list[CaseResult]
    reported_aggregates: dict[str, float] | None = None   # the framework's own headline numbers, keyed by display name, if known
```

Rules: evaluator identity is `EvaluatorRef.id`. Display names are data to be checked, not trusted.
A case-run is the pair `(case_id, run_index)`. Coverage denominators count case-runs whose task did not fail,
unless stated otherwise.

## 6. Checks (MVP: exactly these seven)

Each check returns findings with severity `PASS | WARN | FAIL`, a one-line message, and structured details.
Defaults are deliberately strict; everything is configurable.

| # | Check id | Detects | Default outcome |
|---|---|---|---|
| 1 | `task-failures` | case-runs with `task_error` | FAIL if rate > `--max-task-failure-rate` (0.0). Always report n/N. |
| 2 | `evaluator-coverage` | per evaluator id: case-runs with a non-null value / eligible case-runs | FAIL if any evaluator < `--min-coverage` (1.0). Always print `n/N (pct)` per evaluator. |
| 3 | `evaluator-errors` | per evaluator id: case-runs where `error` is set | FAIL if rate > `--max-evaluator-error-rate` (0.0). Include the most common error message. |
| 4 | `name-collision` | (a) one display name maps to ≥2 evaluator ids across the run; (b) one evaluator id maps to ≥2 display names | FAIL. Message must show the mapping, e.g. `"Judge" → Judge(rubric='strict') on c1; Judge(rubric='lenient') on c2, c3, c4`. |
| 5 | `aggregation-consistency` | per evaluator id (score/assertion): pooled mean over all case-runs vs mean of per-case means; and, if `reported_aggregates` is present, whether the reported number is reproducible from the raw results by either estimator | WARN when the two estimators differ by more than `--aggregation-tolerance` (1e-9), stating both values; FAIL when a reported aggregate matches neither estimator. `--strict-aggregation` turns the WARN into FAIL. |
| 6 | `constant-output` | an evaluator returned the identical value on every eligible case-run, with ≥ `--min-cases-for-constant` (5) case-runs | WARN (likely a stuck judge or a degenerate rubric). |
| 7 | `baseline-comparability` (only with `--baseline`) | case_id sets differ (added/removed); evaluator id sets differ; candidate coverage lower than baseline for any evaluator; different repeat counts | WARN for added/removed cases and evaluator-set differences (FAIL with `--require-same-cases`); FAIL when candidate coverage < baseline coverage for an evaluator; WARN on repeat-count mismatch. |

Overall verdict: `FAIL` if any FAIL finding; `WARN` if only WARN findings (exit 0 unless `--warnings-as-errors`);
`PASS` otherwise.

## 7. Inputs

### 7.1 Generic format (documented in `docs/input-format.md`)

JSON (`{"name": ..., "source": "generic", "cases": [...]}`) or JSONL (one `CaseResult` per line), using the
model in section 5 with `measurements[].evaluator` flattened as `evaluator_id`, `display_name`, `kind`:

```json
{"case_id": "c1", "run_index": 0, "task_error": null,
 "measurements": [{"evaluator_id": "Judge(rubric='strict')", "display_name": "Judge", "kind": "score", "value": 0.0, "error": null}]}
```

### 7.2 pydantic-evals adapter

Input is either an in-memory `EvaluationReport` (Python API) or a JSON file produced by
`pydantic.TypeAdapter(EvaluationReport).dump_json(report, by_alias=True)` (verified to round-trip on
pydantic-ai `main`, Oct 2026). Mapping:

- `cases[].scores | assertions | labels` → measurements. `kind` from the section. `display_name` = the dict key.
  `evaluator.id` = canonical string of `source.name` + `source.arguments` (e.g. `Judge(rubric='strict')`; use
  `json.dumps(arguments, sort_keys=True)` for determinism). **Never derive identity from the dict key.**
- `cases[].evaluator_failures[]` → one measurement per failure with `value=None`, `error=f"{error_type}: {error_message}"`,
  identity from its `source`, `kind` unknown → use `"score"` unless the same identity appears elsewhere with a known kind.
- `failures[]` (top-level task failures) → `CaseResult(task_error=...)`.
- Repeats: when `source_case_name` is set, `case_id = source_case_name` and `run_index` is parsed from the
  ` [i/n]` suffix of `name` (0-based). Otherwise `case_id = name`, `run_index = 0`.
- `reported_aggregates`: only when given the in-memory report, from `report.averages()` (scores, metrics and
  `assertions`), keyed by display name. From JSON, leave `None`.
- `source_version` from `importlib.metadata.version("pydantic-evals")` when available.
- **Identity guard:** if the source metadata needed to recover an evaluator's identity is missing,
  do not silently infer identity from a display key. Report the attribution as unverifiable and
  add an explicit fixture for that case before declaring the adapter production-ready.

### 7.3 promptfoo adapter (stretch, Milestone 5)

Input: `promptfoo eval -o results.json`. Map each result row to a case-run; assertions become `assertion`
measurements with `evaluator.id` built from the assertion type + value; error rows (`failureReason == ERROR`,
`score 0, namedScores {}`) become `task_error`; judge API errors (`metadata.graderError == true`) become
measurement `error`, **not** a FAIL value. Verify every claim here against a real export before coding.

## 8. Interfaces

CLI (argparse, no extra deps):

```
eval-preflight check RESULTS [--format auto|generic|pydantic-evals|promptfoo] [--baseline BASELINE]
    [--min-coverage 1.0] [--max-evaluator-error-rate 0.0] [--max-task-failure-rate 0.0]
    [--aggregation-tolerance 1e-9] [--strict-aggregation] [--min-cases-for-constant 5]
    [--require-same-cases] [--warnings-as-errors] [--json] [--quiet]
```

Exit codes: `0` PASS or WARN-only; `1` FAIL; `2` usage error (bad file, unknown format, bad flags). `--json`
prints a machine-readable report (`{"verdict", "run", "findings": [{check, severity, message, details}]}`) and
nothing else on stdout.

Python API:

```python
from eval_preflight import load, check
result = check(load("results.json"))          # auto-detect format
result = check_pydantic_evals(report, baseline=None)   # in-memory report
result.verdict            # "PASS" | "WARN" | "FAIL"
result.findings           # list[Finding]
result.to_json()
result.raise_if_failed()  # raises IntegrityError with the FAIL findings
```

Terminal output (rich; keep to one screen):

```
eval-preflight  name_shift · 4 cases · pydantic-evals 2.57

FAIL  evaluator-coverage      Judge(rubric='strict') scored 1/4 case-runs (25%)
FAIL  evaluator-errors        Judge(rubric='strict') errored on 3/4: RuntimeError: judge quota exhausted
FAIL  name-collision          "Judge" → Judge(rubric='strict') on c1; Judge(rubric='lenient') on c2, c3, c4
PASS  task-failures           0/4
WARN  constant-output         Judge(rubric='lenient') returned 1.0 on all 4 case-runs
PASS  aggregation-consistency

Verdict: FAIL (3 failures, 1 warning)
```

## 9. Golden scenarios (fixtures; the tool must produce exactly these outcomes)

Fixtures live in `tests/fixtures/`. Hand-written generic fixtures are allowed in Milestone 1; from Milestone 2,
pydantic-evals fixtures must be **generated by running the real library** via `scripts/make_fixtures.py`, and
the script, library version and command are committed next to the fixture. Never hand-edit a generated fixture.

- **A. Partial coverage (#7928).** 4 cases. `FlakyScore` returns 1.0 on `c1`, raises on `c2..c4`.
  `AlwaysScores` returns 0.5 everywhere. Expect: coverage FAIL (`FlakyScore` 1/4), errors FAIL (3/4),
  `AlwaysScores` coverage 4/4 PASS. With the in-memory report: `reported_aggregates["FlakyScore"] == 1.0` is
  reproducible (pooled over 1 case) → the finding must state it is computed from 1 of 4 cases.
- **B. Name shift (#10636).** Two evaluators of class `Judge`, `rubric='strict'` (0.0 on `c1`, raises on
  `c2..c4`) and `rubric='lenient'` (1.0 everywhere). Expect: name-collision FAIL with the mapping
  `"Judge"` → strict on c1, lenient on c2–c4, and `"Judge_2"` → lenient on c1 only; coverage FAIL for strict (1/4).
- **C. Repeat divergence.** 2 cases, `repeat=2`. Case `a` has one assertion that passes; case `b` has three
  that fail. No errors. Expect: aggregation-consistency WARN for the assertion group: pooled 0.25 vs
  mean-of-cases 0.5; with `reported_aggregates["assertions"] == 0.5` the finding states the framework used
  mean-of-cases. Nothing else fails.
- **D. Clean run.** 4 cases, 2 evaluators, no errors, no repeats, varying values. Expect: every check PASS,
  exit 0. This is the no-false-positive guard; keep it in CI forever.
- **E. Baseline.** Baseline = scenario D. Candidate = D minus case `c4`, with one evaluator erroring on `c2`.
  Expect: comparability WARN (removed `c4`), comparability FAIL (coverage dropped 4/4 → 2/3), plus the usual
  coverage/error FAILs.

## 10. Engineering standard

- Python ≥ 3.11. Runtime deps: `pydantic>=2`, `rich`. Nothing else without a written reason. Optional extra
  `pydantic-evals` for the adapter's in-memory path (JSON path must work without it installed).
- Tooling: `uv`, `ruff` (lint + format), `mypy --strict` on `src` and `tests`, `pytest` with coverage ≥ 95% on
  `src`. `make check` runs all four; `make fixtures` regenerates fixtures.
- CI: GitHub Actions on 3.11, 3.12, 3.13 running `make check`. Publishing: a separate workflow on tags `v*`
  using PyPI trusted publishing. Publishing is a deliberate manual tag, never automated on push.
- Layout:

```
src/eval_preflight/{__init__.py, model.py, checks/<one module per check>.py, checks/runner.py,
                    adapters/{generic.py, pydantic_evals.py, promptfoo.py, registry.py}, report.py, cli.py}
tests/{fixtures/, test_model.py, test_checks_<check>.py, test_adapter_<name>.py, test_cli.py, test_golden.py}
scripts/make_fixtures.py   docs/{checks.md, input-format.md, ci.md}   examples/github-action.yml
README.md  CHANGELOG.md  BACKLOG.md  CLAUDE.md  LICENSE (MIT)  pyproject.toml  Makefile
```

- Every check = one module + tests (positive, negative, boundary) + a `docs/checks.md` entry: what it detects,
  why it matters (link the evidence in section 2), default threshold, how to configure, example output.
- README sections: the 10-second problem; install; quickstart (CLI + Python + CI); what it checks (table);
  supported inputs; relation to `evaltrust`/`limen-eval` (complementary, link them); limitations; status: alpha.
  Every behavioural claim in the README must be backed by a test or a cited source.

## 11. Milestones (7–10 days; each ends with CI green and a tag)

- **M1 (days 1–2)**: scaffold, model, generic adapter, CLI skeleton with exit codes, checks 1–4, fixtures A, B,
  D in generic format, `test_golden.py`. Tag `v0.0.1` (no publish). *Done when*: `eval-preflight check` on
  fixture B prints the name-collision mapping and exits 1; fixture D exits 0.
- **M2 (days 3–4)**: pydantic-evals adapter (JSON + in-memory), `scripts/make_fixtures.py`, fixtures A/B/C
  regenerated from real runs, checks 5–6. *Done when*: all golden scenarios A–D pass from generated fixtures.
- **M3 (days 5–6)**: baseline comparability (check 7), `--json`, `examples/github-action.yml`, `docs/` complete.
  *Done when*: scenario E passes and the action example runs in this repo's own CI against fixture D.
- **M4 (day 7)**: first verify/reserve the PyPI distribution name, then README, CHANGELOG, `v0.1.0` on PyPI. *Done when*: `pip install eval-preflight` works in a
  clean venv and the quickstart runs as written.
- **M5 (days 8–10, stretch)**: promptfoo adapter from a real export; dogfood on two public pydantic-evals
  examples; launch write-up (the 9-framework table + the three findings) linked from the README.

## 12. CLAUDE.md (create verbatim)

```markdown
# eval-preflight — working rules

Read SPEC.md before any change. SPEC.md is the contract; this file is how we work.

## Scope
- Build only what SPEC.md lists for the current milestone. New ideas go to BACKLOG.md as one line each.
  Never implement a backlog item unless asked.
- A bug fix is the narrowest change that fixes the reproduced behaviour, plus a regression test.
- The data model in SPEC.md §5 is frozen after v0.1.0. Adapters and checks evolve; the model does not.

## Honesty
- Never fabricate framework behaviour. Adapter claims are verified against fixture files generated by running
  the real framework (scripts/make_fixtures.py), committed with the command and version used.
- Never hand-edit a generated fixture. Regenerate it.
- README and docs claims must be backed by a test or a cited source. Status is "alpha" until told otherwise.
- If a spec item is ambiguous in a way that changes a verdict, stop and ask instead of guessing.

## Quality gate
- `make check` (ruff, mypy --strict, pytest with ≥95% coverage) must be green before every commit and push.
  Never push red. Never skip or weaken a failing test to get green.
- Runtime dependencies are pydantic and rich only. Adding one requires a written reason in the commit message.
- No network calls and no telemetry at runtime, ever.

## Git
- Small commits, one concern each, conventional messages (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
- Push to the working branch freely once green. Publishing to PyPI happens only via a manual `v*` tag.
- Keep CHANGELOG.md current under "Unreleased".

## Tests
- Golden scenarios in SPEC.md §9 are the acceptance tests; scenario D (clean run) must always pass with exit 0.
- Every check has positive, negative and boundary tests. Test through the public API and CLI, not private helpers.
```

## 13. Measuring whether it worked (first 30 days after v0.1.0)

Track weekly in `docs/metrics.md`: PyPI downloads (pypistats), GitHub stars/issues/discussions, number of
feedback conversations, posts and their impressions/profile visits, inbound messages. Targets: one external
user running it in CI (evidence: an issue, PR or mention), three feedback conversations, one issue from a
stranger. Feedback channel: a pinned GitHub Discussion "Did it catch something? Did it miss something?" linked
from the README and from the CLI's FAIL output footer.

## 14. Seed BACKLOG.md with

- Inspect AI `.eval`/`.json` log adapter; deepeval, ragas, LangSmith export adapters.
- `eval-preflight explain <check>` command.
- Per-slice coverage (by metadata key).
- Emit an OpenTelemetry/Logfire attribute set with the verdict.
- Pre-commit hook and a pytest plugin (`assert_integrity(report)`).
- Upstream contributions: pydantic-evals coverage counts (#7928) and name-collision fix (#10636).