"""Evidence-bound classification, without inferred power from model popularity."""

import re

from .schema import Listing


def power(listing: Listing) -> tuple[str, str | None]:
    text = (listing.title + "; " + listing.description).lower()
    if re.search(
        r"\b(?:not|never|isn.t)\s+(?:full[ -]power(?:ed)?|unrestricted|non[ -]lams)\b|\b(?:used to be|was previously|converted|derestricted)\b",
        text,
    ):
        return (
            "UNKNOWN",
            "Negated or modified power claim requires supporting variant evidence",
        )
    positives = list(
        re.finditer(
            r"\b(?:full[ -]power(?:ed)?|unrestricted|not\s+(?:(?:a|an|the)\s+)?lams|non[ -]lams)\b",
            text,
        )
    )
    cleaned = re.sub(
        r"\b(?:not\s+(?:(?:a|an|the)\s+)?lams|non[ -]lams|not\s+(?:learner[ -]approved|restricted)|unrestricted)\b",
        "",
        text,
    )
    negatives = list(
        re.finditer(r"\b(?:lams|learner[ -]approved|restricted|35\s*kw)\b", cleaned)
    )
    # A title saying LAMS remains evidence even when the description contradicts it.
    title = re.sub(
        r"\b(?:not\s+(?:(?:a|an|the)\s+)?lams|non[ -]lams|unrestricted)\b",
        "",
        listing.title.lower(),
    )
    if re.search(r"\b(?:lams|learner[ -]approved|restricted)\b", title):
        negatives.append(True)
    parsed = listing.evidence.get("parsed_power", {})
    if parsed.get("status") == "UNKNOWN" and parsed.get("reason", "").startswith(
        ("Conflicting", "Negated")
    ):
        return "UNKNOWN", parsed["reason"]
    if parsed.get("status") == "RESTRICTED":
        negatives.append(True)
    verified = listing.evidence.get("power", {})
    state = (
        verified.get("status")
        if verified.get("source_url")
        and verified.get("verified_at")
        and verified.get("quotation")
        else None
    )
    if state == "UNRESTRICTED":
        positives.append(True)
    elif state == "RESTRICTED":
        negatives.append(True)
    if positives and negatives:
        return (
            "UNKNOWN",
            "Conflicting restricted and unrestricted evidence; verify variant",
        )
    if negatives:
        return (
            "RESTRICTED",
            "Advert explicitly states LAMS/learner-approved/restricted power",
        )
    if positives:
        quotation = (
            verified.get("quotation") if state else "; ".join(m[0] for m in positives)
        )
        return (
            "UNRESTRICTED",
            f"Explicit evidence: {quotation}; seller claims require verification",
        )
    return "UNKNOWN", "No positive unrestricted-power evidence"
