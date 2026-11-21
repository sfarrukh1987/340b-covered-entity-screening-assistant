"""G1: load saved fixtures. D1: validate each attempted record."""

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit

from .contracts import StrictModel, json_object

MAX_HTML = 1_000_000
CSV_FIELDS = (
    "candidate_id", "name", "state", "city", "ZIP", "source_url", "registry_date",
    "page_date", "ce_id", "registry_status", "source_confirmed", "html_file",
)
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}")
ZIP = re.compile(r"[0-9]{5}")
CITY = re.compile(r"[A-Za-z][A-Za-z .'-]{0,99}")


class SourceRecord(StrictModel):
    candidate_id: str
    name: str
    state: str
    city: str
    ZIP: str
    source_url: str
    registry_date: str
    page_date: str
    HTML: str
    ce_id: str | None
    registry_status: Literal["active", "inactive", "unknown"]


@dataclass(frozen=True)
class Config:
    location: str
    max_candidates: int
    as_of: date


@dataclass(frozen=True)
class AttemptInput:
    record: dict
    html_file: str
    source_confirmed: bool
    error: str | None = None


@dataclass(frozen=True)
class Bundle:
    config: Config
    records: list[AttemptInput]
    corrections: dict[str, AttemptInput]


def iso_date(value: str) -> date:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Dates must use YYYY-MM-DD.")
    return date.fromisoformat(value)


def load_config(text: str) -> Config:
    config = json_object(text)
    if set(config) != {"synthetic", "location", "max_candidates", "as_of"}:
        raise ValueError("Use the four documented configuration fields.")
    if config["synthetic"] is not True:
        raise ValueError("This rough draft only accepts synthetic bundles.")
    loc, limit, reference = config["location"], config["max_candidates"], config["as_of"]
    if not isinstance(loc, str) or not (CITY.fullmatch(loc) or ZIP.fullmatch(loc)):
        raise ValueError("Location must be a city name or a five-digit ZIP.")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("max_candidates must be an integer from 1 to 10.")
    if not isinstance(reference, str):
        raise ValueError("as_of must be a date string.")
    return Config(loc, limit, iso_date(reference))


def _read(root: Path, file: Path, limit: int) -> str:
    path = file.resolve()
    if not path.is_relative_to(root):
        raise ValueError("Input files must stay within the bundle.")
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Input exceeds its size limit.")
    return data.decode("utf-8")


def _attempt(root: Path, row: dict[str, str]) -> AttemptInput:
    record = {k: v for k, v in row.items() if k not in ("source_confirmed", "html_file")}
    record["ce_id"] = record["ce_id"] or None
    record["registry_status"] = record["registry_status"] or "unknown"
    name = row["html_file"]
    error = None
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,59}\.html", name):
            raise ValueError("Use a saved local .html filename.")
        parent = (root / "pages").resolve()
        if not parent.is_relative_to(root) or parent == root:
            raise ValueError("Saved pages must be in the bundle's pages directory.")
        record["HTML"] = _read(parent, parent / name, 4 * MAX_HTML)
    except (OSError, ValueError, RuntimeError):
        record["HTML"] = None
        error = "The saved HTML page is missing, unreadable, outside the bundle, or too large."
    return AttemptInput(record, name, row["source_confirmed"] == "true", error)


def _csv(root: Path, filename: str, limit: int) -> dict[str, AttemptInput]:
    reader = csv.DictReader(_read(root, root / filename, 64_000).splitlines(keepends=True), strict=True)
    fields = reader.fieldnames or []
    if len(fields) != len(CSV_FIELDS) or set(fields) != set(CSV_FIELDS):
        raise ValueError(f"{filename} must have the documented columns, each once.")
    result = {}
    for row in reader:
        if len(result) >= limit or None in row or None in row.values():
            raise ValueError(f"{filename} contains too many rows or an invalid row shape.")
        candidate_id = row["candidate_id"]
        if not ID.fullmatch(candidate_id) or candidate_id in result:
            raise ValueError(f"{filename} requires valid, unique candidate IDs.")
        result[candidate_id] = _attempt(root, row)
    return result


def load_bundle(directory: Path) -> Bundle:
    root = directory.resolve()
    config = load_config(_read(root, root / "config.json", 16_000))
    records = _csv(root, "records.csv", config.max_candidates)
    if not records:
        raise ValueError("Supply at least one synthetic candidate.")
    corrections_path = root / "corrections.csv"
    fixes = _csv(root, "corrections.csv", config.max_candidates) if corrections_path.exists() else {}
    if not fixes.keys() <= records.keys():
        raise ValueError("Corrections must refer to existing candidate IDs.")
    return Bundle(config, list(records.values()), fixes)


def _synthetic_url(value: str) -> bool:
    if len(value) > 500 or any(ord(c) < 33 for c in value):
        return False
    url = urlsplit(value)
    return (
        url.scheme == "https"
        and re.fullmatch(r"(?:[a-z0-9][a-z0-9-]*\.)+example", url.netloc.lower()) is not None
        and not url.fragment
    )


def check_record(item: AttemptInput, as_of: date) -> tuple[SourceRecord, list[str]]:
    if not item.source_confirmed:
        raise ValueError("Confirm that the OPAIS snapshot and official page refer to the same entity.")
    record = SourceRecord.model_validate(item.record)
    if not ID.fullmatch(record.candidate_id):
        raise ValueError("The candidate ID is invalid.")
    if not record.name.strip() or len(record.name) > 160:
        raise ValueError("A short nonblank organization name is required.")
    if record.state != "NY" or not CITY.fullmatch(record.city) or not ZIP.fullmatch(record.ZIP):
        raise ValueError("A New York location with a city and a five-digit ZIP is required.")
    if not _synthetic_url(record.source_url):
        raise ValueError("The source must use an HTTPS .example URL in this demonstration.")
    if len(record.HTML) > MAX_HTML:
        raise ValueError("The saved page exceeds 1,000,000 HTML characters.")
    if iso_date(record.page_date) > as_of:
        raise ValueError("Page capture date is after the reference date.")
    if record.registry_date and iso_date(record.registry_date) > as_of:
        raise ValueError("Registry capture date is after the reference date.")
    if record.ce_id is not None and not ID.fullmatch(record.ce_id):
        raise ValueError("The registry ID is invalid.")
    missing = []
    if not record.ce_id:
        missing.append("ce_id")
    if not record.registry_date:
        missing.append("registry_date")
    if record.registry_status == "unknown":
        missing.append("registry_status")
    return record, missing
