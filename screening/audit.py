"""D5: check the explanation and produce escaped local audit and CSV output."""

import csv
import html
import io
import json

from .contracts import Evidence, Explanation

ACTION_ORDER = {"review": 0, "verify": 1, "hold": 2}
CSV_FIELDS = ("candidate_id", "name", "city", "ZIP", "source_url", "action",
              "reasons", "explanation", "attempts", "model_calls", "error_steps")


def check_explanation(explanation: Explanation, screen: dict, evidence: Evidence) -> None:
    expected_sources = list(dict.fromkeys(item.source_url for item in evidence.services))
    if (
        explanation.candidate_id != screen["candidate_id"]
        or explanation.action != screen["action"]
        or explanation.citations != expected_sources
        or explanation.rationale != " ".join(screen["reasons"])
    ):
        raise ValueError("Explanation changed an ID, action, approved reason, or citation.")


def _sheet(value: object) -> str:
    text = str(value)
    # CSV quoting alone does not stop a spreadsheet treating text as a formula.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def render_reports(rows: list[dict], metadata: dict) -> tuple[str, str]:
    rows = sorted(rows, key=lambda row: (
        ACTION_ORDER[row["screen"]["action"]], row["record"]["name"].casefold(),
        row["record"]["candidate_id"],
    ))
    report = io.StringIO(newline="")
    writer = csv.DictWriter(report, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    entries = []
    for row in rows:
        record, screen = row["record"], row["screen"]
        description = " ".join(screen["reasons"])
        explanation = (row["explanation"] or {}).get("rationale", "")
        sheet = {key: record[key] for key in ("candidate_id", "name", "city", "ZIP", "source_url")}
        sheet.update(action=screen["action"], reasons=description, explanation=explanation,
                     attempts=len(row["attempts"]), model_calls=row["model_calls"],
                     error_steps="; ".join(e["step"] for e in row["errors"]))
        writer.writerow({key: _sheet(val) for key, val in sheet.items()})
        details = html.escape(json.dumps(row, indent=2, ensure_ascii=False))
        heading = html.escape(f'{record["candidate_id"]}: {record["name"]} — {screen["action"]}')
        entries.append(
            f"<section><h2>{heading}</h2><p>{html.escape(description)}</p>"
            f"<details><summary>Sources, attempts, checks and errors</summary><pre>{details}</pre></details>"
            "</section>"
        )
    summary = ", ".join(f"{label}: {sum(r['screen']['action'] == label for r in rows)}" for label in ACTION_ORDER)
    meta = html.escape(json.dumps(metadata, ensure_ascii=False, indent=2))
    audit = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>340B Screening Assistant — Synthetic Audit</title>'
        '<style>body{font:1rem system-ui,sans-serif;max-width:66rem;margin:2rem auto;padding:0 1rem}'
        'section{border-top:1px solid #ccc;margin:1.2rem 0;padding:.3rem 0}'
        'h2{font-size:1.15rem}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head>'
        '<body><h1>340B Screening Assistant — Synthetic Audit</h1>'
        '<p>Course demonstration. These research labels do not determine eligibility or contracting. '
        'A person must check the original sources before any action.</p>'
        f'<p>{len(rows)} candidates ({summary}).</p>'
        f'<details><summary>Run metadata</summary><pre>{meta}</pre></details>'
        + "".join(entries) + "</body></html>\n"
    )
    return audit, report.getvalue()
