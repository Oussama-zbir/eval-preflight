"""In-memory EvaluationReport path, run against the real pydantic-evals (dev group)."""

import importlib.metadata
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic_evals import Case, Dataset, increment_eval_metric

from eval_preflight import check, check_pydantic_evals, from_pydantic_evals, load
from tests.scenarios import SCENARIOS, run_scenario

FIXTURES = Path(__file__).parent / "fixtures" / "pydantic_evals"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_in_memory_matches_the_generated_json(scenario: str) -> None:
    in_memory = from_pydantic_evals(run_scenario(scenario))
    from_json = load(FIXTURES / f"{scenario}.json")
    assert in_memory.cases == from_json.cases
    assert in_memory.name == from_json.name
    assert in_memory.source == "pydantic-evals"


def test_fixtures_were_generated_with_the_installed_version() -> None:
    # Otherwise the equality above compares two different library versions.
    installed = importlib.metadata.version("pydantic-evals")
    assert (FIXTURES / "VERSION").read_text().strip() == f"pydantic-evals=={installed}"


def test_source_version_and_reported_aggregates_come_from_the_report() -> None:
    run = from_pydantic_evals(run_scenario("clean_run"))
    assert run.source_version == importlib.metadata.version("pydantic-evals")
    assert run.reported_aggregates == {"Relevance": pytest.approx(0.6375), "assertions": 0.75}


def test_name_shift_aggregates_hide_the_shift_but_checks_do_not() -> None:
    run = from_pydantic_evals(run_scenario("name_shift"))
    # pydantic-evals reports "Judge" as strict on c1 averaged with lenient on c2..c4.
    assert run.reported_aggregates == {"Judge": 0.75, "Judge_2": 1.0}
    result = check(run)
    reproduced = [
        f for f in result.by_check("aggregation-consistency") if "reported_key" in f.details
    ]
    assert {f.severity for f in reproduced} == {"PASS"}
    assert {f.severity for f in result.by_check("name-collision")} == {"FAIL"}


def test_metrics_are_reported_but_cannot_be_checked() -> None:
    async def task(inputs: str) -> str:
        increment_eval_metric("tokens", 10)
        return inputs

    dataset = Dataset[str, str, None](name="metrics", cases=[Case(name="c1", inputs="x")])
    report = dataset.evaluate_sync(task, progress=False)
    run = from_pydantic_evals(report)
    assert run.reported_aggregates == {"tokens": 10}
    (finding,) = check(run).by_check("aggregation-consistency")
    assert finding.severity == "WARN"
    assert "cannot be checked" in finding.message


def test_check_pydantic_evals_takes_a_config() -> None:
    from eval_preflight import CheckConfig

    report = run_scenario("partial_coverage")
    assert check_pydantic_evals(report).verdict == "FAIL"
    relaxed = CheckConfig(min_coverage=0.25, max_evaluator_error_rate=0.75)
    assert check_pydantic_evals(report, relaxed).verdict == "PASS"


def test_rejects_objects_that_are_not_reports() -> None:
    with pytest.raises(TypeError, match="expected a pydantic_evals EvaluationReport"):
        from_pydantic_evals({"cases": []})  # type: ignore[arg-type]


def test_missing_extra_gives_an_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pydantic_evals", None)
    monkeypatch.setitem(sys.modules, "pydantic_evals.reporting", None)
    with pytest.raises(ImportError, match=r"pip install 'eval-preflight\[pydantic-evals\]'"):
        from_pydantic_evals(object())  # type: ignore[arg-type]


def test_json_path_never_imports_pydantic_evals() -> None:
    code = (
        "import sys\n"
        "sys.modules['pydantic_evals'] = None\n"
        "from eval_preflight import check, load\n"
        f"result = check(load({str(FIXTURES / 'clean_run.json')!r}))\n"
        "assert result.verdict == 'PASS', result.verdict\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_report_where_every_task_failed_has_no_aggregates() -> None:
    async def task(inputs: str) -> str:
        raise RuntimeError("model down")

    dataset = Dataset[str, str, None](name="down", cases=[Case(name="c1", inputs="x")])
    run = from_pydantic_evals(dataset.evaluate_sync(task, progress=False))
    assert run.reported_aggregates == {}
    assert [(c.case_id, c.task_error) for c in run.cases] == [("c1", "RuntimeError: model down")]
    assert check(run).verdict == "FAIL"
