from eval_preflight import EvalRun, Finding, check
from tests.builders import case, m, run


def findings(result_run: EvalRun) -> list[Finding]:
    return check(result_run).by_check("name-collision")


def test_stable_names_pass() -> None:
    [finding] = findings(
        run(
            case("c1", m("a", 1.0, display="A"), m("b", 0.0, display="B")),
            case("c2", m("a", 1.0, display="A"), m("b", 0.0, display="B")),
        )
    )
    assert finding.severity == "PASS"


def test_display_name_shared_by_two_ids_fails_with_mapping() -> None:
    [by_name, by_id] = findings(
        run(
            case("c1", m("strict", 0.0, display="Judge"), m("lenient", 1.0, display="Judge_2")),
            case("c2", m("lenient", 1.0, display="Judge")),
            case("c3", m("lenient", 1.0, display="Judge")),
        )
    )
    assert by_name.severity == "FAIL"
    assert by_name.message == '"Judge" → strict on c1; lenient on c2, c3'
    assert by_name.details == {
        "kind": "display_name_to_ids",
        "display_name": "Judge",
        "mapping": {"strict": ["c1"], "lenient": ["c2", "c3"]},
    }
    assert by_id.severity == "FAIL"
    assert by_id.message == 'lenient → "Judge_2" on c1; "Judge" on c2, c3'
    assert by_id.details["kind"] == "id_to_display_names"


def test_two_ids_sharing_a_name_within_one_case_run_fail() -> None:
    [finding] = findings(run(case("c1", m("x(1)", 1.0, display="X"), m("x(2)", 0.0, display="X"))))
    assert finding.severity == "FAIL"
    assert finding.message == '"X" → x(1) on c1; x(2) on c1'


def test_measurements_without_value_do_not_count_as_a_filed_name() -> None:
    # The failed evaluator keeps its display name, but nothing was filed under it.
    [finding] = findings(
        run(
            case("c1", m("strict", 0.0, display="Judge")),
            case("c2", m("strict", None, display="Judge_2", error="boom")),
        )
    )
    assert finding.severity == "PASS"


def test_long_case_lists_are_truncated_in_message_but_not_details() -> None:
    cases = [case("c0", m("a", 1.0, display="N"))] + [
        case(f"c{i}", m("b", 1.0, display="N")) for i in range(1, 11)
    ]
    [finding] = findings(run(*cases))
    assert finding.message == '"N" → a on c0; b on c1, c2, c3, c4, c5 (+5 more)'
    assert len(finding.details["mapping"]["b"]) == 10


def test_repeat_labels_include_run_index() -> None:
    [finding, _] = findings(
        run(
            case("a", m("x", 1.0, display="N"), run_index=0),
            case("a", m("y", 1.0, display="N"), m("x", 1.0, display="N_2"), run_index=1),
        )
    )
    assert finding.message == '"N" → x on a[0]; y on a[1]'
