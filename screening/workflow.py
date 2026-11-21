"""G2: route candidates, retain attempts, stop on errors, and save the reports."""

from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
import platform

from .audit import check_explanation, render_reports
from .contracts import MAX_REPLY, json_object, validate_evidence, validate_explanation
from .inputs import Bundle, check_record
from .model_steps import (
    Backend, EXPLANATION_VERSION, EXTRACTION_VERSION, explain_result, extract_services,
)
from .parsing import parse_html, service_section
from .rules import screen_candidate

MODEL_TEXT_LIMIT = 16_000


def _metadata(item) -> dict:
    return {k: v for k, v in item.record.items() if k != "HTML"} | {
        "html_file": item.html_file, "source_confirmed": item.source_confirmed,
    }


def _audit_reply(raw: object) -> str | None:
    if not isinstance(raw, str) or len(raw) > MAX_REPLY:
        return None
    return raw.encode("utf-8", errors="backslashreplace").decode("utf-8")


def _run_candidate(item, correction, config, backend: Backend) -> dict:
    candidate_id = item.record["candidate_id"]
    row = {
        "record": _metadata(item), "attempts": [], "errors": [], "model_calls": 0,
        "raw_evidence": None, "evidence": None, "screen": None,
        "raw_explanation": None, "explanation": None,
    }

    def error(step: str, message: str, attempt: int, *, detail: bool = True) -> None:
        record = {"candidate_id": candidate_id, "step": step, "message": message[:600], "attempt": attempt}
        row["errors"].append(record)
        if detail:
            row["attempts"][-1]["errors"].append(record.copy())

    def verify(message: str) -> dict:
        return {"candidate_id": candidate_id, "action": "verify", "reasons": [message]}

    def complete(request) -> str:
        row["model_calls"] += 1
        return backend.complete(request)

    for number, entry in enumerate([item, correction] if correction is not None else [item], 1):
        row["record"] = _metadata(entry)
        attempt = {"number": number, "input": row["record"], "clean_text": None,
                   "service_text": None, "missing": [], "errors": []}
        row["attempts"].append(attempt)
        if entry.error:
            error("G1", entry.error, number)
            continue
        try:
            record, missing = check_record(entry, config.as_of)
            attempt["missing"] = missing
        except ValueError as exc:
            error("D1", str(exc), number)
            continue
        try:
            full_text = parse_html(record.HTML)
            text = service_section(record.HTML)
            attempt.update(clean_text=full_text, service_text=text)
            if not text:
                raise ValueError("No service text extracted; this does not establish absence of services.")
            if len(text) > MODEL_TEXT_LIMIT:
                raise ValueError("Saved service text is too long for the demonstration model step.")
        except ValueError as exc:
            error("A1", str(exc), number)
            continue
        if missing:
            error("D1", f"Missing registry information: {', '.join(missing)}.", number)
            continue
        break
    else:
        row["screen"] = verify("The saved inputs remain incomplete or invalid; review the attempts.")
        return row

    step = "D2"
    try:
        raw = extract_services(complete, record, text)
        step = "A2 evidence"
        row["raw_evidence"] = _audit_reply(raw)
        evidence = validate_evidence(json_object(raw))
        row["evidence"] = evidence.model_dump()
        step = "D3"
        row["screen"] = screen_candidate(record, config, full_text, text, evidence)
        step = "D4"
        raw = explain_result(complete, evidence, row["screen"])
        step = "A2 explanation"
        row["raw_explanation"] = _audit_reply(raw)
        explanation = validate_explanation(json_object(raw))
        step = "D5"
        check_explanation(explanation, row["screen"], evidence)
        row["explanation"] = explanation.model_dump()
    except ValueError as exc:
        error(step, str(exc), number, detail=False)
        if row["screen"] is None:
            row["screen"] = verify("The evidence could not be verified; inspect the audit before use.")
    return row


def run_workflow(bundle: Bundle, backend: Backend) -> tuple[list[dict], dict]:
    started = datetime.now(timezone.utc)
    rows = [
        _run_candidate(item, bundle.corrections.get(item.record["candidate_id"]), bundle.config, backend)
        for item in bundle.records
    ]
    metadata = {
        "scope": "synthetic teaching demonstration",
        "model_id": backend.model_id, "model_settings": backend.settings,
        "prompts": {"D2": EXTRACTION_VERSION, "D4": EXPLANATION_VERSION},
        "location": bundle.config.location, "as_of": bundle.config.as_of.isoformat(),
        "started_utc": started.isoformat(), "finished_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "versions": {name: version(name) for name in ("beautifulsoup4", "pydantic")},
    }
    return rows, metadata


def write_reports(directory: Path, rows: list[dict], metadata: dict) -> None:
    audit, shortlist = render_reports(rows, metadata)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "audit.html").write_text(audit, encoding="utf-8", newline="\n")
    (directory / "shortlist.csv").write_text(shortlist, encoding="utf-8", newline="\n")
