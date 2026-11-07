"""promptfoo adapter.

Fixtures are real exports (promptfoo 0.125.1, scripts/make_promptfoo_fixtures.py). Edge
cases edit a copy of a generated row, so their shape stays the one promptfoo writes.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from eval_preflight import LoadError, check, load
from eval_preflight.adapters.registry import detect
from eval_preflight.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "promptfoo"
CONTAINS = "contains('answer')"
NONEMPTY = "javascript('output.length > 3')"
RUBRIC = "llm-rubric('is polite')"
SET_CHILDREN = ("icontains('ANSWER')", "starts-with('answer')")


def export(name: str = "clean_run") -> dict[str, Any]:
    document: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return document


def row(name: str = "clean_run", index: int = 0) -> dict[str, Any]:
    return copy.deepcopy(export(name)["results"]["results"][index])


def with_rows(tmp_path: Path, *rows: dict[str, Any], **results: Any) -> Path:
    document = export()
    document["results"]["results"] = list(rows)
    document["results"].update(results)
    path = tmp_path / "results.json"
    path.write_text(json.dumps(document))
    return path


def components(r: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = r["gradingResult"]["componentResults"]
    return found


@pytest.mark.parametrize("name", ["clean_run", "judge_errors", "task_errors"])
def test_generated_exports_are_detected(name: str) -> None:
    text = (FIXTURES / f"{name}.json").read_text()
    assert detect(text) == "promptfoo"
    run = load(FIXTURES / f"{name}.json")
    assert (run.name, run.source, run.source_version) == (name, "promptfoo", "0.125.1")
    assert run.reported_aggregates is None


def test_repeats_become_run_indices_and_assertions_become_measurements() -> None:
    run = load(FIXTURES / "clean_run.json")
    assert sorted((c.case_id, c.run_index) for c in run.cases) == [
        (case, index) for case in ("c1", "c2", "c3", "c4") for index in (0, 1)
    ]
    refs = {m.evaluator.id: m.evaluator for c in run.cases for m in c.measurements}
    # The assert-set's summary entry is skipped; its two children are measurements.
    assert set(refs) == {CONTAINS, NONEMPTY, RUBRIC, *SET_CHILDREN}
    assert all(len(c.measurements) == 5 for c in run.cases)
    assert {r.kind for r in refs.values()} == {"assertion"}
    # The display name is the metric promptfoo aggregates under, else the id.
    assert refs[NONEMPTY].display_name == "nonempty"
    assert refs[CONTAINS].display_name == CONTAINS
    assert all(m.value is True and m.error is None for c in run.cases for m in c.measurements)


def test_judge_errors_are_measurement_errors_not_failed_assertions() -> None:
    # promptfoo itself reports this run as 1 pass, 3 failures and 0 errors.
    stats = export("judge_errors")["results"]["stats"]
    assert (stats["successes"], stats["failures"], stats["errors"]) == (1, 3, 0)

    run = load(FIXTURES / "judge_errors.json")
    rubric = {c.case_id: m for c in run.cases for m in c.measurements if m.evaluator.id == RUBRIC}
    assert rubric["c1"].value is True and rubric["c1"].error is None
    for case in ("c2", "c3", "c4"):
        assert rubric[case].value is None
        assert rubric[case].error == "judge quota exhausted"
    assert all(c.task_error is None for c in run.cases)


def test_provider_errors_are_task_errors_without_measurements() -> None:
    run = load(FIXTURES / "task_errors.json")
    failed = [c for c in run.cases if c.task_error is not None]
    assert [(c.case_id, c.task_error, c.measurements) for c in failed] == [
        ("c3", "Error: upstream timeout", [])
    ]


@pytest.mark.parametrize(
    ("name", "code", "failing"),
    [
        ("clean_run", 0, set()),
        ("judge_errors", 1, {"evaluator-coverage", "evaluator-errors"}),
        ("task_errors", 1, {"task-failures"}),
    ],
)
def test_verdicts_on_generated_exports(
    name: str, code: int, failing: set[str], capsys: pytest.CaptureFixture[str]
) -> None:
    result = check(load(FIXTURES / f"{name}.json"))
    assert {f.check for f in result.findings if f.severity == "FAIL"} == failing
    assert not [f for f in result.findings if f.severity == "WARN"]
    assert main(["check", str(FIXTURES / f"{name}.json"), "--format", "promptfoo"]) == code
    capsys.readouterr()


def test_baseline_against_itself_is_comparable() -> None:
    path = str(FIXTURES / "clean_run.json")
    assert main(["check", path, "--baseline", path]) == 0


def test_assertion_failure_with_error_text_is_not_a_task_error(tmp_path: Path) -> None:
    # promptfoo also sets the row's `error` when an assertion fails; only failureReason 2
    # is a task error.
    r = row()
    r.update(failureReason=1, success=False, error="Expected output to contain 'answer'")
    components(r)[0].update({"pass": False, "score": 0})
    case = load(with_rows(tmp_path, r)).cases[0]
    assert case.task_error is None
    assert [m.value for m in case.measurements] == [False, True, True, True, True]


def test_assert_set_summary_entry_is_in_the_export() -> None:
    entries = components(row())
    summaries = [e for e in entries if e.get("assertion") is None]
    assert [e["metadata"]["assertionSet"]["type"] for e in summaries] == ["assert-set"]
    assert len(entries) == 6


def test_case_id_falls_back_to_sorted_vars(tmp_path: Path) -> None:
    r = row()
    r["testCase"].pop("description")
    r["vars"] = {"q": "c1", "a": 1}
    assert load(with_rows(tmp_path, r)).cases[0].case_id == '{"a": 1, "q": "c1"}'


def test_missing_repeat_index_is_run_zero(tmp_path: Path) -> None:
    r = row(index=1)
    assert r["repeatIndex"] == 1
    r.pop("repeatIndex")
    assert load(with_rows(tmp_path, r)).cases[0].run_index == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "is-json()"),
        (["a", "b"], 'is-json(["a", "b"])'),
        ({"b": 1, "a": 2}, 'is-json({"a": 2, "b": 1})'),
        (0.5, "is-json(0.5)"),
    ],
)
def test_evaluator_id_from_type_and_value(tmp_path: Path, value: Any, expected: str) -> None:
    r = row()
    assertion = {"type": "is-json"} if value is None else {"type": "is-json", "value": value}
    r["gradingResult"]["componentResults"] = [components(r)[0] | {"assertion": assertion}]
    ref = load(with_rows(tmp_path, r)).cases[0].measurements[0].evaluator
    assert (ref.id, ref.display_name) == (expected, expected)


def test_shared_metric_name_is_a_name_collision(tmp_path: Path) -> None:
    # promptfoo sums both assertions into one named score, so "quality" means two things.
    r = row()
    components(r)[0]["assertion"]["metric"] = "quality"
    components(r)[1]["assertion"]["metric"] = "quality"
    result = check(load(with_rows(tmp_path, r)))
    collisions = [f for f in result.findings if f.check == "name-collision"]
    assert [f.severity for f in collisions] == ["FAIL"]
    assert collisions[0].details["display_name"] == "quality"


def test_same_assertion_twice_in_one_test_is_rejected(tmp_path: Path) -> None:
    r = row()
    components(r).append(copy.deepcopy(components(r)[0]))
    with pytest.raises(LoadError, match="duplicate evaluator id"):
        load(with_rows(tmp_path, r))


def test_several_providers_are_rejected(tmp_path: Path) -> None:
    other = row(index=2)
    other["provider"] = {"id": "other-model", "label": ""}
    with pytest.raises(LoadError, match="2 prompt/provider combinations"):
        load(with_rows(tmp_path, row(), other))


def test_several_prompts_are_rejected(tmp_path: Path) -> None:
    other = row(index=2)
    other["promptIdx"] = 1
    with pytest.raises(LoadError, match="combinations"):
        load(with_rows(tmp_path, row(), other))


def test_grader_error_without_reason(tmp_path: Path) -> None:
    r = row()
    components(r)[2].update({"pass": False, "score": 0, "metadata": {"graderError": True}})
    components(r)[2].pop("reason")
    measurement = load(with_rows(tmp_path, r)).cases[0].measurements[2]
    assert (measurement.value, measurement.error) == (None, "grader error")


def test_task_error_without_message(tmp_path: Path) -> None:
    r = row()
    r.update(failureReason=2, gradingResult=None)
    r.pop("error", None)
    assert load(with_rows(tmp_path, r)).cases[0].task_error == "task error"


def test_row_without_grading_result_has_no_measurements(tmp_path: Path) -> None:
    r = row()
    r["gradingResult"] = None
    assert load(with_rows(tmp_path, r)).cases[0].measurements == []


def test_name_falls_back_to_file_stem(tmp_path: Path) -> None:
    document = export()
    del document["config"]["description"]
    del document["metadata"]["promptfooVersion"]
    path = tmp_path / "nightly.json"
    path.write_text(json.dumps(document))
    run = load(path)
    assert (run.name, run.source_version) == ("nightly", None)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["results"].update(version=2), "unsupported promptfoo results version 2"),
        (lambda d: d["results"].update(results=[]), "no case results"),
        (lambda d: d.update(results=[]), "no `results` object"),
        (
            lambda d: d["results"]["results"][0].update(repeatIndex=-1),
            "invalid promptfoo result row",
        ),
        (
            lambda d: d["results"]["results"][0]["gradingResult"]["componentResults"][0].pop(
                "pass"
            ),
            "has no `pass` value",
        ),
    ],
)
def test_malformed_exports_are_load_errors(tmp_path: Path, mutate: Any, message: str) -> None:
    document = export()
    mutate(document)
    path = tmp_path / "results.json"
    path.write_text(json.dumps(document))
    with pytest.raises(LoadError, match=message):
        load(path, format="promptfoo")


def test_invalid_json_is_a_load_error(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text("{not json")
    with pytest.raises(LoadError, match="not valid JSON"):
        load(path, format="promptfoo")


def test_cli_exit_2_on_unsupported_export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = export()
    document["results"]["version"] = 4
    path = tmp_path / "results.json"
    path.write_text(json.dumps(document))
    assert main(["check", str(path)]) == 2
    assert "unsupported promptfoo results version" in capsys.readouterr().err
