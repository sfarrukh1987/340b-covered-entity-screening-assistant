"""D3: enforce source identity and apply the research rules."""

from .contracts import Evidence
from .inputs import Config, SourceRecord, ZIP, iso_date
from .model_steps import SERVICE_QUOTES


def screen_candidate(record: SourceRecord, config: Config, full_text: str,
                     service_text: str, evidence: Evidence) -> dict:
    if evidence.candidate_id != record.candidate_id:
        raise ValueError("The evidence candidate ID does not match.")
    for service in evidence.services:
        if service.source_url != record.source_url:
            raise ValueError("An evidence URL does not match the supplied source.")
        if not service.quote.strip() or service.quote not in service_text or service.quote not in full_text:
            raise ValueError("An evidence quote is absent from the saved service text.")

    def result(action: str, *reasons: str) -> dict:
        return {"candidate_id": record.candidate_id, "action": action, "reasons": list(reasons)}

    site = record.ZIP if ZIP.fullmatch(config.location) else record.city
    if site.casefold() != config.location.casefold():
        return result("hold", "The recorded site does not match the selected city or ZIP.")
    if record.registry_status == "inactive":
        return result("hold", "The saved registry record is inactive.")
    if not record.registry_date or not record.ce_id or record.registry_status != "active":
        return result("verify", "Registry information is incomplete.")
    if (config.as_of - iso_date(record.registry_date)).days > 30:
        return result("verify", "The saved registry record is more than 30 days old.")
    if evidence.missing:
        return result("verify", "The model marked evidence as missing; review the saved source.")
    if not any(
        service.code in ("primary_care", "behavioral_health")
        and SERVICE_QUOTES[service.code] in service.quote
        for service in evidence.services
    ):
        return result("verify", "No verified primary care or behavioral health sentence was found in the saved service text.")
    return result("review", "The saved registry is active and current, the location matches, and an exact service quote is present.")
