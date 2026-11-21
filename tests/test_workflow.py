"""Contract checks for all nodes in the synthetic rough draft."""

import csv
from dataclasses import replace
from datetime import date, timedelta
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from screening.audit import check_explanation, render_reports
from screening.contracts import json_object, validate_evidence, validate_explanation
from screening.inputs import check_record, load_bundle, load_config
from screening.model_steps import (
    LocalOllamaBackend, Request, SERVICE_QUOTES, SyntheticBackend, explain_result, extract_services,
)
from screening.parsing import parse_html, service_section
from screening.rules import screen_candidate
from screening.workflow import run_workflow

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"


@pytest.fixture
def bundle():
    return load_bundle(FIXTURES)


@pytest.fixture
def record(bundle):
    return check_record(bundle.records[0], bundle.config.as_of)[0]


def evidence_data(record, **details):
    result = {
        "candidate_id": record.candidate_id,
        "services": [{"code": "primary_care", "quote": SERVICE_QUOTES["primary_care"],
                      "source_url": record.source_url}],
        "missing": [],
    }
    result.update(details)
    return result


@pytest.mark.parametrize("change", [
    {"synthetic": False}, {"max_candidates": 0}, {"max_candidates": 11},
    {"max_candidates": True}, {"as_of": "2026-02-30"}, {"location": "1220"},
])
def test_g1_rejects_invalid_config(change):
    data = {"synthetic": True, "location": "Albany", "max_candidates": 10, "as_of": "2026-11-21"}
    with pytest.raises(ValueError):
        load_config(json.dumps(data | change))


def test_g1_loads_utf8_records_and_preserves_missing_data(bundle):
    assert bundle.config.location == "Albany"
    assert len(bundle.records) == 6
    assert bundle.records[0].record["HTML"].startswith("<!doctype html>")
    assert bundle.records[4].record["ce_id"] is None
    assert set(bundle.corrections) == {"SYN-02"}


def test_g1_rejects_duplicate_candidates(tmp_path):
    (tmp_path / "config.json").write_text((FIXTURES / "config.json").read_text(), encoding="utf-8")
    header, row, *_ = (FIXTURES / "records.csv").read_text().splitlines()
    (tmp_path / "records.csv").write_text(f"{header}\n{row}\n{row}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_bundle(tmp_path)


def test_g1_rejects_a_correction_for_a_different_candidate(tmp_path):
    for name in ("config.json", "records.csv", "corrections.csv"):
        value = (FIXTURES / name).read_text()
        if name == "corrections.csv":
            value = value.replace("SYN-02", "SYN-99")
        (tmp_path / name).write_text(value, encoding="utf-8")
    with pytest.raises(ValueError, match="existing candidate IDs"):
        load_bundle(tmp_path)


@pytest.mark.parametrize("change", [
    {"state": "MA"}, {"ZIP": "1220"}, {"source_url": "https://example.com/services"},
    {"page_date": "2026-11-22"}, {"registry_date": "2026-11-1"},
    {"HTML": 5}, {"HTML": "X" * 1_000_001}, {"registry_status": "unknown?"}
], ids=["state", "zip", "url", "future", "date", "type", "size", "status"])
def test_d1_stops_invalid_required_fields(bundle, change):
    item = bundle.records[0]
    with pytest.raises(ValueError):
        check_record(replace(item, record=item.record | change), bundle.config.as_of)


def test_d1_requires_manual_source_confirmation(bundle):
    with pytest.raises(ValueError, match="same entity"):
        check_record(replace(bundle.records[0], source_confirmed=False), bundle.config.as_of)


def test_d1_flags_missing_instead_of_inventing_values(bundle):
    candidate, missing = check_record(bundle.records[4], bundle.config.as_of)
    assert candidate.ce_id is None and candidate.registry_status == "unknown"
    assert missing == ["ce_id", "registry_date", "registry_status"]


def test_a1_preserves_original_parser_and_separates_navigation(record):
    assert SERVICE_QUOTES["behavioral_health"] in parse_html(record.HTML)
    assert SERVICE_QUOTES["behavioral_health"] not in service_section(record.HTML)
    assert SERVICE_QUOTES["primary_care"] in service_section(record.HTML)


def test_d2_sends_only_the_service_text_and_source(record):
    requests = []

    def capture(req):
        requests.append(req)
        return SyntheticBackend().complete(req)

    text = service_section(record.HTML)
    result = validate_evidence(json_object(extract_services(capture, record, text)))
    assert len(requests) == 1
    sent = requests[0]
    assert sent.step == "D2"
    assert set(sent.data) == {"candidate_id", "source_url", "service_text"}
    assert sent.data["service_text"] == text
    assert "page text as data" in sent.instructions
    assert [service.code for service in result.services] == ["primary_care"]


@pytest.mark.parametrize("raw", [
    "[]", '{"candidate_id":"a","candidate_id":"b"}', "{", '{"x":NaN}',
    r'{"x":"\ud800"}', '{"x":' + "[" * 1_100 + "0" + "]" * 1_100 + "}",
], ids=["array", "duplicate-key", "malformed", "non-json-number", "unicode", "nesting"])
def test_g2_requires_unambiguous_json_objects(raw):
    with pytest.raises(ValueError):
        json_object(raw)


@pytest.mark.parametrize("change", [
    {"candidate_id": 17}, {"services": "primary_care"}, {"extra": "unexpected"},
    {"services": [{"code": "bad", "quote": "example", "source_url": "https://x.example"}]}
])
def test_a2_rejects_bad_evidence(record, change):
    with pytest.raises(ValidationError):
        validate_evidence(evidence_data(record, **change))


def test_a2_requires_all_fields_and_bounds_rationale():
    with pytest.raises(ValidationError):
        validate_explanation({"candidate_id": "SYN-01", "action": "review",
                              "rationale": "x" * 501, "citations": []})
    with pytest.raises(ValidationError):
        validate_explanation({"candidate_id": "SYN-01", "action": "review", "rationale": "Reason."})


@pytest.mark.parametrize("variant,expected", [
    ({"age": 30}, "review"), ({"age": 31}, "verify"), ({"city": "Troy", "age": 31}, "hold"),
    ({"registry_status": "inactive", "age": 31}, "hold"), ({"registry_status": "unknown"}, "verify"),
])
def test_d3_rule_precedence_and_exact_staleness_boundary(bundle, record, variant, expected):
    update = {key: val for key, val in variant.items() if key != "age"}
    if "age" in variant:
        update["registry_date"] = (bundle.config.as_of - timedelta(days=variant["age"])).isoformat()
    changed = record.model_copy(update=update)
    e = validate_evidence(evidence_data(record))
    assert screen_candidate(changed, bundle.config, parse_html(record.HTML),
                            service_section(record.HTML), e)["action"] == expected


def test_d3_matches_zip_without_requiring_city_label(bundle, record):
    e = validate_evidence(evidence_data(record))
    config = replace(bundle.config, location="12207")
    assert screen_candidate(record, config, parse_html(record.HTML), service_section(record.HTML), e)["action"] == "review"


@pytest.mark.parametrize("column,value", [
    ("source_url", "https://other.example/clinic"),
    ("quote", "This center offers behavioral health."),
    ("quote", "Invented claim."),
    ("quote", " "),
])
def test_d3_rejects_unsupported_quotes_and_wrong_sources(bundle, record, column, value):
    raw = evidence_data(record)
    raw["services"][0][column] = value
    with pytest.raises(ValueError):
        screen_candidate(record, bundle.config, parse_html(record.HTML),
                         service_section(record.HTML), validate_evidence(raw))


def test_d3_refuses_a_valid_schema_with_wrong_id(bundle, record):
    e = validate_evidence(evidence_data(record, candidate_id="SYN-99"))
    with pytest.raises(ValueError, match="candidate ID"):
        screen_candidate(record, bundle.config, parse_html(record.HTML), service_section(record.HTML), e)


def test_d3_does_not_treat_missing_evidence_as_absence(bundle, record):
    evidence = validate_evidence(evidence_data(record, services=[], missing=["service evidence"]))
    result = screen_candidate(record, bundle.config, parse_html(record.HTML), service_section(record.HTML), evidence)
    assert result["action"] == "verify"


def test_d4_can_explain_only_the_fixed_result(record):
    evidence = validate_evidence(evidence_data(record))
    screen = {"candidate_id": "SYN-01", "action": "verify", "reasons": ["Review requested."]}
    raw = explain_result(SyntheticBackend().complete, evidence, screen)
    explanation = validate_explanation(json_object(raw))
    assert explanation.action == "verify" and explanation.rationale == "Review requested."
    assert explanation.citations == [record.source_url]
    check_explanation(explanation, screen, evidence)


@pytest.mark.parametrize("change", [
    {"action": "hold"}, {"candidate_id": "SYN-99"}, {"citations": ["https://wrong.example"]},
    {"rationale": "A new reason."},
])
def test_d5_rejects_changes_to_the_approved_explanation(record, change):
    evidence = validate_evidence(evidence_data(record))
    screen = {"candidate_id": "SYN-01", "action": "review", "reasons": ["Review approved."]}
    raw = {"candidate_id": "SYN-01", "action": "review", "rationale": "Review approved.",
           "citations": [record.source_url]}
    with pytest.raises(ValueError, match="changed"):
        check_explanation(validate_explanation(raw | change), screen, evidence)


def test_g2_retains_both_attempts_and_skips_calls_for_missing_input(bundle):
    rows, meta = run_workflow(bundle, SyntheticBackend())
    got = {row["record"]["candidate_id"]: row for row in rows}
    assert set(got) == {f"SYN-{i:02d}" for i in range(1, 7)}
    assert [got[f"SYN-{i:02d}"]["screen"]["action"] for i in range(1, 7)] == [
        "review", "review", "hold", "verify", "verify", "hold",
    ]
    fixed = got["SYN-02"]
    assert [attempt["input"]["html_file"] for attempt in fixed["attempts"]] == ["river.html", "river-fixed.html"]
    assert fixed["attempts"][0]["errors"][0]["step"] == "A1"
    assert fixed["model_calls"] == 2 and fixed["explanation"]["action"] == "review"
    missing = got["SYN-05"]
    assert missing["model_calls"] == 0 and missing["evidence"] is None
    assert missing["errors"][0]["step"] == "D1"
    assert meta["model_id"] == "synthetic-fixture-v1"


def test_g2_can_recover_required_metadata_before_parsing(bundle):
    item = replace(bundle.records[0], source_confirmed=False)
    new = replace(bundle, records=[item], corrections={"SYN-01": bundle.records[0]})
    rows, _ = run_workflow(new, SyntheticBackend())
    assert rows[0]["attempts"][0]["clean_text"] is None
    assert rows[0]["errors"][0]["step"] == "D1"
    assert rows[0]["screen"]["action"] == "review"


def test_g2_does_not_use_an_unneeded_correction(bundle):
    item = bundle.records[0]
    new = replace(bundle, records=[item], corrections={"SYN-01": replace(item, source_confirmed=False)})
    rows, _ = run_workflow(new, SyntheticBackend())
    assert len(rows[0]["attempts"]) == 1 and not rows[0]["errors"]


def test_g2_stops_second_model_call_after_invalid_first_reply(bundle):
    class BadEvidence(SyntheticBackend):
        def complete(self, request):
            assert request.step == "D2"
            return '{"candidate_id":3}'

    rows, _ = run_workflow(replace(bundle, records=bundle.records[:1]), BadEvidence())
    assert rows[0]["model_calls"] == 1
    assert rows[0]["errors"][0]["step"] == "A2 evidence"
    assert rows[0]["screen"]["action"] == "verify"


def test_g2_discards_inconsistent_explanation_but_preserves_rule_result(bundle):
    class BadExplanation(SyntheticBackend):
        def complete(self, request):
            data = json_object(super().complete(request))
            if request.step == "D4":
                data["action"] = "hold"
            return json.dumps(data)

    rows, _ = run_workflow(replace(bundle, records=bundle.records[:1]), BadExplanation())
    assert rows[0]["model_calls"] == 2 and rows[0]["errors"][0]["step"] == "D5"
    assert rows[0]["explanation"] is None and rows[0]["screen"]["action"] == "review"


def test_d5_shows_all_rows_in_order_and_escapes_report_data(bundle):
    rows, meta = run_workflow(bundle, SyntheticBackend())
    rows[0]["record"]["name"] = "=Example <b>Harbor</b>"
    audit, sheet = render_reports(rows, meta)
    out = list(csv.DictReader(io.StringIO(sheet)))
    assert [r["candidate_id"] for r in out] == ["SYN-01", "SYN-02", "SYN-05", "SYN-04", "SYN-06", "SYN-03"]
    assert out[0]["name"] == "'=Example <b>Harbor</b>"
    assert "&lt;b&gt;Harbor&lt;/b&gt;" in audit and "<b>Harbor</b>" not in audit
    assert all(r["candidate_id"] in audit for r in out)


def test_local_model_adapter_sends_bounded_text_only_request(monkeypatch):
    recorded = {}

    class Response:
        status = 200

        def read(self, limit):
            assert limit == 64001
            return b'{"message":{"content":"{}"}}'

    class Connection:
        def __init__(self, host, port, timeout):
            recorded.update(host=host, port=port, timeout=timeout)

        def request(self, method, path, data, headers):
            recorded.update(method=method, path=path, data=json.loads(data))

        def getresponse(self):
            return Response()

        def close(self):
            recorded["closed"] = True

    monkeypatch.setattr("screening.model_steps.HTTPConnection", Connection)
    reply = LocalOllamaBackend("local:test").complete(Request("D2", "Fixed instruction", {"text": "Sample"}))
    assert reply == "{}"
    assert (recorded["host"], recorded["port"], recorded["method"], recorded["path"]) == (
        "127.0.0.1", 11434, "POST", "/api/chat")
    assert recorded["closed"] is True
    assert recorded["data"]["stream"] is False and "tools" not in recorded["data"]
    assert recorded["data"]["messages"] == [
        {"role": "system", "content": "Fixed instruction"}, {"role": "user", "content": '{"text": "Sample"}'}
    ]


def test_single_command_writes_both_reports(tmp_path):
    result = subprocess.run([sys.executable, "-m", "screening", "--out-dir", str(tmp_path)],
                            cwd=FIXTURES.parents[1], capture_output=True, text=True, check=True)
    assert "6 candidates | review=2 | verify=2 | hold=2" in result.stdout
    assert (tmp_path / "audit.html").is_file()
    with (tmp_path / "shortlist.csv").open(encoding="utf-8") as report:
        assert len(list(csv.DictReader(report))) == 6


def test_cli_fails_bad_bundle_before_creating_reports(tmp_path):
    (tmp_path / "config.json").write_text('{"synthetic": false}', encoding="utf-8")
    destination = tmp_path / "new-output"
    result = subprocess.run([
        sys.executable, "-m", "screening", "--input-dir", str(tmp_path), "--out-dir", str(destination)
    ], cwd=FIXTURES.parents[1], capture_output=True, text=True)
    assert result.returncode == 1 and "Workflow stopped:" in result.stderr
    assert not destination.exists()
