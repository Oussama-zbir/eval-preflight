import json
from pathlib import Path
from typing import Any

import pytest

from eval_preflight import LoadError, load

FIXTURES = Path(__file__).parent / "fixtures"


def line(case_id: str, *measurements: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"case_id": case_id, "measurements": list(measurements), **extra}


def meas(evaluator_id: str, value: Any, **extra: Any) -> dict[str, Any]:
    return {
        "evaluator_id": evaluator_id,
        "display_name": evaluator_id,
        "kind": "score",
        "value": value,
        **extra,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_json_fixture_maps_flattened_evaluator_fields() -> None:
    result = load(FIXTURES / "name_shift.json")
    assert result.name == "name_shift"
    assert result.source == "generic"
    assert len(result.cases) == 4
    first = result.cases[0].measurements[0]
    assert first.evaluator.id == "Judge(rubric='strict')"
    assert first.evaluator.display_name == "Judge"
    assert first.evaluator.kind == "score"
    assert first.value == 0.0


def test_json_optional_run_fields(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    path.write_text(
        json.dumps(
            {
                "name": "r",
                "source": "generic",
                "source_version": "1.2",
                "reported_aggregates": {"e": 0.5},
                "cases": [line("c1", meas("e", 0.5))],
            }
        )
    )
    result = load(path, format="generic")
    assert result.source_version == "1.2"
    assert result.reported_aggregates == {"e": 0.5}


def test_jsonl_one_case_result_per_line(tmp_path: Path) -> None:
    path = write_jsonl(
        tmp_path / "my_run.jsonl",
        [
            line("c1", meas("e", 1.0)),
            line("c1", meas("e", 0.0), run_index=1),
            line("c2", task_error="boom"),
        ],
    )
    result = load(path)
    assert result.name == "my_run"
    assert result.source == "generic"
    assert [(c.case_id, c.run_index) for c in result.cases] == [("c1", 0), ("c1", 1), ("c2", 0)]
    assert result.cases[2].task_error == "boom"


def test_jsonl_blank_lines_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    path.write_text(json.dumps(line("c1")) + "\n\n" + json.dumps(line("c2")) + "\n")
    assert len(load(path).cases) == 2


def test_single_line_jsonl_is_detected(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "r.jsonl", [line("c1", meas("e", 1.0))])
    assert load(path).cases[0].case_id == "c1"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "no case results"),
        ("{not json", "not valid JSON"),
        ('{"name": "r", "source": "promptfoo", "cases": []}', "could not detect"),
        ("[1, 2]", "could not detect"),
        ('{"case_id": "c1"}\n{oops\n', "line 2: not valid JSON"),
        ('{"case_id": "c1"}\n[1]\n', "line 2: expected a JSON object"),
    ],
)
def test_unreadable_or_unrecognised_content(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "r.json"
    path.write_text(content)
    with pytest.raises(LoadError, match=message):
        load(path)


def test_schema_errors_name_the_offending_line(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "r.jsonl", [line("c1"), line("c2", meas("e", 1.0, kind="x"))])
    with pytest.raises(LoadError, match="line 2"):
        load(path)


def test_unknown_measurement_field_is_rejected(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "r.jsonl", [line("c1", meas("e", 1.0, evaluator="e"))])
    with pytest.raises(LoadError, match="evaluator"):
        load(path)


def test_explicit_generic_format_rejects_other_sources(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"name": "r", "source": "promptfoo", "cases": []}))
    with pytest.raises(LoadError, match="source must be 'generic'"):
        load(path, format="generic")


def test_invalid_json_document_names_the_problem(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"name": "r", "source": "generic", "cases": [{"run_index": 0}]}))
    with pytest.raises(LoadError, match=r"invalid generic document(.|\n)*case_id"):
        load(path)


def test_json_document_without_cases_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"name": "r", "source": "generic", "cases": []}))
    with pytest.raises(LoadError, match="no case results"):
        load(path)


def test_duplicate_case_runs_are_rejected(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "r.jsonl", [line("c1"), line("c1")])
    with pytest.raises(LoadError, match="duplicate case-run"):
        load(path)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(LoadError, match="cannot read"):
        load(tmp_path / "missing.json")


def test_unknown_format_name(tmp_path: Path) -> None:
    with pytest.raises(LoadError, match="unknown format 'csv'"):
        load(FIXTURES / "clean_run.json", format="csv")
