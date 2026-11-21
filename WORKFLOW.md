# Instructions for reproducing the screening workflow

Rebuild the orchestration around the documented inputs and outputs. Keep node contracts and observable behavior; private helper names and internal layout may change. Run `python -m pytest -v` and `python -m screening` from the repository root to check the reconstruction.

## Inputs and run contract

- The CLI defaults to `fixtures/synthetic` and `outputs`; `--input-dir` and `--out-dir` replace these directories. One `python -m screening` run writes `audit.html` and `shortlist.csv`, prints the counts in review, verify, hold order, and exits 0. A malformed bundle stops with a short diagnostic and a nonzero exit. Per-candidate errors stay in the reports.
- `config.json` is UTF-8 JSON with a `synthetic` flag set to true, a city or five-digit ZIP in `location`, integer `max_candidates` from 1 to 10, and an explicit `as_of` date. `records.csv` contains 1 to `max_candidates` uniquely identified synthetic rows. `corrections.csv` is optional and uses the same columns and only existing IDs, at most one row per ID.
- CSV columns: `candidate_id`, `name`, `state`, `city`, `ZIP`, `source_url`, `registry_date`, `page_date`, `ce_id`, `registry_status`, `source_confirmed`, `html_file`. Read saved UTF-8 files from `pages/` only; accept `.html` basenames and reject paths outside the bundle. No URLs are fetched. The CSV filename and confirmation are fixture metadata; the typed record holds decoded `HTML`.
- A human confirms the source pair by entering `true`. `state` must be `NY`; IDs and ZIPs must have the documented shape; the URL must be HTTPS with a synthetic `.example` hostname. Required captures use `YYYY-MM-DD` and cannot be after `as_of`. Missing registry date is the empty string, missing `ce_id` is null, and missing status becomes `unknown`; preserve these gaps. Accept at most 1,000,000 decoded HTML characters per page and 16,000 service-text characters for the model step. No inputs contain patient information.

## Node contracts

| Node | Code | Behavior |
|---|---|---|
| G1 | `inputs.py: load_bundle` | Decode the saved config, records, page files and optional correction rows. Reject malformed or duplicate bundle records; attach file-read errors to the candidate attempt. |
| D1 | `inputs.py: check_record` | Validate required metadata and explicit pairing. Return the typed record and a list of missing registry fields. Invalid required values stop this attempt before A1. |
| A1 | `parsing.py: parse_html` | Use `BeautifulSoup(html, 'html.parser').get_text(' ', strip=True)` exactly. Preserve the full text for audit. A separate service view removes navigation/header/footer and prefers main content. Neither executes JavaScript. |
| D2 | `model_steps.py: extract_services` | One fixed text-only request per admitted candidate. Send only candidate ID, public source URL label and scoped text as data. Request `candidate_id`, `services`, and `missing`; each service has `code`, `quote`, `source_url`. |
| A2 | `contracts.py` | Parse bounded JSON objects without duplicate fields. Use strict Pydantic models with required keys and no extras, for both evidence and explanation. This checks structure. |
| D3 | `rules.py: screen_candidate` | Confirm returned ID and URL; every quote must match both scoped and full text exactly. Hold for known location mismatch or inactive registration. Otherwise verify when registry data/evidence are incomplete, the snapshot is over 30 days old, or an exact qualifying primary care or behavioral health sentence is missing. Otherwise review. These are research labels. |
| D4 | `model_steps.py: explain_result` | One request with the validated evidence and fixed rule output. Return `candidate_id`, `action`, `rationale` (at most 500 characters), `citations`. Join approved reasons without adding claims. |
| D5 | `audit.py` | Confirm explanation ID, action, reasons and citations. Discard and log an inconsistent explanation; keep the deterministic decision. Sort all rows by review, verify, hold, then case-insensitive name and ID. Render escaped HTML and neutralize spreadsheet formula prefixes in CSV text. |
| G2 | `workflow.py: run_workflow`, `write_reports` | Apply the correction and error routing below, record metadata, and write both local files. |

## Routing and audit

1. For each initial row, record an attempt with its identifiers, source and dates. Run D1 and A1; log bad metadata, unreadable files, missing registry data, empty or too long service text. If input needs correction and a human supplied one replacement for that exact ID, record a second attempt and repeat validation and parsing once. Otherwise keep `verify`, include both attempts if present, and skip model calls. Ignore unused corrections.
2. Once input is ready, call D2, parse its JSON, run A2, then run D3. On any failure, log an error with the node, candidate ID, attempt and reason; keep `verify` and skip D4. If these pass, call D4, parse, validate with A2, then run the D5 consistency check. On an explanation failure, keep the D3 action, omit that explanation and retain the error.
3. Keep every candidate in both reports. Store saved-file identifiers, full/scoped text, raw replies when within size limits, validated outputs, fixed decision, discarded explanation failures, and a timestamp, model settings, prompt versions and package versions. Show a human-review notice. Escape data in HTML; don't turn unverified sources into executable links.
4. In default mode use deterministic replies under the same model interface: text extraction recognizes the invented full service sentences in the fixture, and explanation copies the approved action and joins rule reasons. This mode uses no credentials or network. The optional local adapter is text only with no tool definitions and no remote host setting. Do not deploy a live workflow or run with protected data.

The fixtures exercise a successful source match, a saved-page correction, incomplete and stale evidence, geographic mismatch, and inactive registration. Their expected ordered outcomes are two review, two verify, two hold; the error and correction details must remain in the audit. See `docs/workflow.md` for the current diagram.
