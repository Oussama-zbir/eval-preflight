"""pydantic-evals JSON adapter. Shapes mirror the generated fixtures (pydantic-evals 2.61.0)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from eval_preflight import EvalRun, LoadError, load
from eval_preflight.adapters.registry import detect

FIXTURES = Path(__file__).parent / "fixtures" / "pydantic_evals"


def result(
    name: str, value: float | bool | str, arguments: Any = None, *, source: str | None = None
) -> dict[str, Any]:
    """A result; `source` differs from `name` for a named output of a multi-output evaluator."""
    return {
        "name": name,
        "value": value,
        "reason": None,
        "source": {"name": source or name, "arguments": arguments},
    }


def failure(
    name: str, message: str, error_type: str, arguments: Any = None, *, source: str | None = None
) -> dict[str, Any]:
    return {
        "name": name,
        "error_message": message,
        "error_stacktrace": "...",
        "source": {"name": source or name, "arguments": arguments},
        "error_type": error_type,
    }


def report_case(name: str, **sections: Any) -> dict[str, Any]:
    return {
        "name": name,
        "inputs": name,
        "scores": {},
        "assertions": {},
        "labels": {},
        "source_case_name": None,
        "evaluator_failures": [],
        **sections,
    }


def report(*cases: dict[str, Any], failures: Any = (), **extra: Any) -> dict[str, Any]:
    return {
        "name": "task",
        "cases": list(cases),
        "failures": list(failures),
        "dataset_name": "ds",
        **extra,
    }


def load_doc(tmp_path: Path, document: object, format: str = "auto") -> EvalRun:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return load(path, format=format)


def test_identity_comes_from_source_not_the_display_key(tmp_path: Path) -> None:
    run = load_doc(
        tmp_path,
        report(report_case("c1", scores={"Judge": result("Judge", 1.0, ["lenient"])})),
    )
    (m,) = run.cases[0].measurements
    assert m.evaluator.id == "Judge('lenient')"
    assert m.evaluator.display_name == "Judge"
    assert m.evaluator.kind == "score"
    assert m.value == 1.0


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (None, "E()"),
        ({}, "E()"),
        # pydantic-evals' compact form: one non-default value in the first dataclass field,
        # serialized without its name. Rendered positionally; no key is invented.
        (["x"], "E('x')"),
        ([1.5], "E(1.5)"),
        ([True], "E(True)"),
        ([None], "E(None)"),
        ([[1, "a"]], "E([1, 'a'])"),
        (["it's"], 'E("it\'s")'),
        ({"rubric": "strict", "model": "m", "n": 2}, "E(model='m', n=2, rubric='strict')"),
        ({"cfg": {"b": 1, "a": [1, 2]}}, "E(cfg={'a': [1, 2], 'b': 1})"),
        ({"cfg": [{"z": None, "y": False}]}, "E(cfg=[{'y': False, 'z': None}])"),
    ],
)
def test_evaluator_id_is_canonical(tmp_path: Path, arguments: Any, expected: str) -> None:
    run = load_doc(tmp_path, report(report_case("c1", scores={"E": result("E", 0.5, arguments)})))
    assert run.cases[0].measurements[0].evaluator.id == expected


def test_dict_key_order_does_not_change_the_id(tmp_path: Path) -> None:
    a = {"cfg": {"a": 1, "b": 2}, "rubric": "x"}
    b = {"rubric": "x", "cfg": {"b": 2, "a": 1}}
    ids = {
        load_doc(tmp_path, report(report_case("c1", scores={"E": result("E", 0.5, args)})))
        .cases[0]
        .measurements[0]
        .evaluator.id
        for args in (a, b)
    }
    assert ids == {"E(cfg={'a': 1, 'b': 2}, rubric='x')"}


def test_named_outputs_get_one_id_per_output(tmp_path: Path) -> None:
    run = load_doc(
        tmp_path,
        report(
            report_case(
                "c1",
                assertions={
                    "fmt": result("fmt", True, source="Checks"),
                    "len": result("len", False, source="Checks"),
                },
                scores={"Checks": result("Checks", 0.5, source="Checks")},
            )
        ),
    )
    got = [(m.evaluator.id, m.evaluator.display_name) for m in run.cases[0].measurements]
    assert got == [("Checks()", "Checks"), ("Checks()[fmt]", "fmt"), ("Checks()[len]", "len")]


def test_named_output_id_uses_result_name_not_the_deduplicated_key(tmp_path: Path) -> None:
    # Two outputs called "ok" from different evaluators: pydantic-evals files the second
    # one under "ok_2", but each keeps its own source and output name.
    run = load_doc(
        tmp_path,
        report(
            report_case(
                "c1",
                assertions={
                    "ok": result("ok", True, source="A"),
                    "ok_2": result("ok", False, source="B"),
                },
            )
        ),
    )
    got = [(m.evaluator.id, m.evaluator.display_name) for m in run.cases[0].measurements]
    assert got == [("A()[ok]", "ok"), ("B()[ok]", "ok_2")]


def test_failure_of_a_renamed_evaluator_keeps_the_same_id(tmp_path: Path) -> None:
    # An evaluator whose default evaluation name differs from its class name reports
    # results and failures under that name, so both map to one id.
    run = load_doc(
        tmp_path,
        report(
            report_case("c1", scores={"tone": result("tone", 1.0, ["tone"], source="Judge")}),
            report_case(
                "c2",
                evaluator_failures=[failure("tone", "E: x", "E", ["tone"], source="Judge")],
            ),
        ),
    )
    ids = [m.evaluator.id for c in run.cases for m in c.measurements]
    assert ids == ["Judge('tone')[tone]", "Judge('tone')[tone]"]
    assert run.cases[1].measurements[0].evaluator.kind == "score"


def test_sections_map_to_kinds(tmp_path: Path) -> None:
    run = load_doc(
        tmp_path,
        report(
            report_case(
                "c1",
                scores={"S": result("S", 0.5)},
                assertions={"A": result("A", True)},
                labels={"L": result("L", "good")},
            )
        ),
    )
    got = {(m.evaluator.id, m.evaluator.kind, m.value) for m in run.cases[0].measurements}
    assert got == {("S()", "score", 0.5), ("A()", "assertion", True), ("L()", "label", "good")}


def test_evaluator_failure_becomes_an_error_measurement(tmp_path: Path) -> None:
    run = load_doc(
        tmp_path,
        report(
            report_case("c1", assertions={"A": result("A", True)}),
            report_case(
                "c2",
                evaluator_failures=[
                    failure("A", "RuntimeError: quota", "RuntimeError"),
                    failure("Unseen", "boom", "ValueError"),
                ],
            ),
        ),
    )
    known, unseen = run.cases[1].measurements
    assert (known.evaluator.id, known.evaluator.kind) == ("A()", "assertion")
    assert known.value is None
    assert known.error == "RuntimeError: quota"
    # Never scored anywhere, so its kind is unknown and defaults to "score" (SPEC §7.2).
    assert (unseen.evaluator.id, unseen.evaluator.kind) == ("Unseen()", "score")
    assert unseen.error == "ValueError: boom"


def test_task_failures_become_task_errors(tmp_path: Path) -> None:
    run = load_doc(
        tmp_path,
        report(
            report_case("ok", scores={"S": result("S", 1.0)}),
            failures=[{"name": "bad", "source_case_name": None, "error_message": "ValueError: x"}],
        ),
    )
    bad = run.cases[1]
    assert (bad.case_id, bad.run_index, bad.task_error) == ("bad", 0, "ValueError: x")
    assert bad.measurements == []


def test_repeats_parse_case_id_and_zero_based_run_index(tmp_path: Path) -> None:
    run = load_doc(
        tmp_path,
        report(
            report_case("a [1/2]", source_case_name="a"),
            report_case("a [2/2]", source_case_name="a"),
            failures=[{"name": "b [2/2]", "source_case_name": "b", "error_message": "E: x"}],
        ),
    )
    assert [(c.case_id, c.run_index) for c in run.cases] == [("a", 0), ("a", 1), ("b", 1)]


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("a", "no matching ' [i/n]' repeat suffix"),
        ("other [1/2]", "no matching ' [i/n]' repeat suffix"),
        ("a [3/2]", "repeat index 3 outside 1..2"),
        ("a [0/2]", "repeat index 0 outside 1..2"),
    ],
)
def test_malformed_repeat_names_are_rejected(tmp_path: Path, name: str, message: str) -> None:
    with pytest.raises(LoadError, match=re.escape(message)):
        load_doc(tmp_path, report(report_case(name, source_case_name="a")))


@pytest.mark.parametrize("section", ["scores", "evaluator_failures"])
def test_missing_source_is_unverifiable_not_guessed(tmp_path: Path, section: str) -> None:
    if section == "scores":
        entry: Any = {"S": {"name": "S", "value": 1.0}}
    else:
        entry = [{"name": "S", "error_message": "E: x", "error_type": "E"}]
    with pytest.raises(LoadError, match="has no source metadata"):
        load_doc(tmp_path, report(report_case("c1", **{section: entry})))


def test_run_name_prefers_dataset_name(tmp_path: Path) -> None:
    case = report_case("c1", scores={"S": result("S", 1.0)})
    assert load_doc(tmp_path, report(case)).name == "ds"
    assert load_doc(tmp_path, report(case, dataset_name=None)).name == "task"
    assert load_doc(tmp_path, report(case, dataset_name=None, name="")).name == "report"


def test_source_and_no_reported_aggregates_from_json(tmp_path: Path) -> None:
    run = load_doc(tmp_path, report(report_case("c1", scores={"S": result("S", 1.0)})))
    assert run.source == "pydantic-evals"
    assert run.source_version is None
    assert run.reported_aggregates is None


def test_auto_detects_generated_fixtures() -> None:
    for path in sorted(FIXTURES.glob("*.json")):
        assert detect(path.read_text(encoding="utf-8")) == "pydantic-evals"


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (report(), "no case results in input"),
        ({"cases": []}, "not a pydantic-evals report"),
        ([1, 2], "not a pydantic-evals report"),
        (report({"name": "c1", "scores": "nope"}), "invalid pydantic-evals report"),
        (
            report(report_case("c1"), report_case("c1")),
            "duplicate case-run",
        ),
    ],
)
def test_invalid_reports_raise_load_error(tmp_path: Path, document: object, message: str) -> None:
    with pytest.raises(LoadError, match=message):
        load_doc(tmp_path, document, format="pydantic-evals")


def test_explicit_format_rejects_non_json(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(LoadError, match="not valid JSON"):
        load(path, format="pydantic-evals")
