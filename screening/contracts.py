"""A2: validate replies after both model steps."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Action = Literal["review", "verify", "hold"]
ServiceCode = Literal["primary_care", "behavioral_health", "dental", "other"]
Text = Annotated[str, StringConstraints(min_length=1, max_length=500)]
MAX_REPLY = 16_000


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class Service(StrictModel):
    code: ServiceCode
    quote: Text
    source_url: Text


class Evidence(StrictModel):
    candidate_id: Text
    services: list[Service]
    missing: list[Text]


class Explanation(StrictModel):
    candidate_id: Text
    action: Action
    rationale: Text
    citations: list[Text]


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("A JSON object contains a duplicate field.")
        result[key] = value
    return result


def _non_json(_: str) -> None:
    raise ValueError("A non-JSON numeric value was supplied.")


def json_object(text: str, max_size: int = MAX_REPLY) -> dict:
    if not isinstance(text, str) or len(text) > max_size:
        raise ValueError("Expected a bounded JSON string.")
    try:
        result = json.loads(text, object_pairs_hook=_pairs, parse_constant=_non_json)
        pending = [(result, 0)]
        while pending:
            value, depth = pending.pop()
            if depth > 16:
                raise ValueError("The JSON structure is too deeply nested.")
            if isinstance(value, dict):
                pending.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                pending.extend((item, depth + 1) for item in value)
        json.dumps(result, ensure_ascii=False).encode("utf-8")
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("The JSON contains excessive nesting or invalid Unicode.") from exc
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object.")
    return result


def validate_evidence(raw: dict) -> Evidence:
    return Evidence.model_validate(raw)


def validate_explanation(raw: dict) -> Explanation:
    return Explanation.model_validate(raw)
