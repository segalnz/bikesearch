"""Model-independent purchase requirements; unknown mandatory facts need review."""

import re
from urllib.parse import urlsplit

from .classification import power
from .normalization import utc_now


def advert_facts(text: str) -> dict:
    """Only explicit units/wording are evidence; dry weight is never wet weight."""
    facts = {}
    patterns = {
        "cylinders": r"\b([1-9])[- ]cylinder\b",
        "power_hp": r"\b(\d+(?:\.\d+)?)\s*(?:bhp|hp|horsepower)\b",
        "wet_weight_kg": r"\b(?:wet|kerb|curb|ready[- ]to[- ]ride)\s*(?:weight)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*kg\b",
        "seat_height_mm": r"\bseat\s*height\s*[:=]?\s*(\d{3})\s*mm\b",
    }
    for field, pattern in patterns.items():
        matches = list(re.finditer(pattern, text, re.I))
        values = {float(match[1]) for match in matches}
        if len(values) == 1:
            facts[field] = {"value": values.pop(), "quotation": matches[0][0]}
    wet_matches = list(re.finditer(patterns["wet_weight_kg"], text, re.I)) + list(
        re.finditer(r"\b(\d+(?:\.\d+)?)\s*kg\s*(?:wet|kerb|curb)\b", text, re.I)
    )
    wet_values = {float(match[1]) for match in wet_matches}
    if len(wet_values) == 1:
        facts["wet_weight_kg"] = {
            "value": wet_values.pop(),
            "quotation": wet_matches[0][0],
        }
    else:
        facts.pop("wet_weight_kg", None)
    if "power_hp" not in facts:
        match = re.search(r"\b(\d+(?:\.\d+)?)\s*kw\b", text, re.I)
        if match:
            facts["power_hp"] = {
                "value": round(float(match[1]) * 1.34102209, 1),
                "quotation": match[0],
            }
    if "cylinders" not in facts:
        engines = list(
            re.finditer(
                r"\b(parallel[- ]twin|v[- ]twin|inline[- ]twin|twin[- ]cylinder|triple[- ]cylinder|inline[- ]triple|inline[- ]four|four[- ]cylinder|single[- ]cylinder)\b",
                text,
                re.I,
            )
        )
        values = {
            3
            if "triple" in m[0].lower()
            else 4
            if "four" in m[0].lower()
            else 1
            if "single" in m[0].lower()
            else 2
            for m in engines
        }
        if len(values) == 1:
            facts["cylinders"] = {"value": values.pop(), "quotation": engines[0][0]}
    if re.search(
        r"\b(?:no|without|non[- ]|not fitted with|not)\s*abs\b|\babs\s+(?:removed|disabled|fault|not working|not fitted|not present)\b",
        text,
        re.I,
    ):
        facts["abs"] = {
            "value": False,
            "quotation": "Advert says ABS absent/disabled/faulty",
        }
    elif re.search(r"\babs\b", text, re.I) and not re.search(
        r"\b(?:optional|available)\s+abs\b|\babs\s+(?:is\s+)?(?:optional|available|option)\b",
        text,
        re.I,
    ):
        facts["abs"] = {
            "value": True,
            "quotation": "ABS explicitly mentioned in advert; confirm operation",
        }
    if re.search(
        r"\b(?:factory|standard|original)\s+(?:screen|windscreen|fairing)|\b(?:half|full)[- ]fairing\b",
        text,
        re.I,
    ):
        facts["weather_protection"] = {
            "value": True,
            "quotation": "Advert explicitly describes factory screen/fairing",
        }
    if re.search(r"\benglish\b", text, re.I) and re.search(
        r"\b(?:workshop|service)\s+manual\s+(?:included|available|supplied)\b",
        text,
        re.I,
    ):
        facts["english_manual"] = {
            "value": True,
            "quotation": "Advert states English workshop/service manual included/available",
        }
    if re.search(
        r"\b(?:diy|home)[- ](?:serviceable|servicing|maintenance)|\bowner[- ]serviceable\b",
        text,
        re.I,
    ):
        facts["diy_serviceable"] = {
            "value": True,
            "quotation": "Advert explicitly claims owner/DIY serviceability",
        }
    if re.search(
        r"\b(?:no|without)\s+(?:english\s+)?(?:workshop|service)\s+manual|\bmanual\s+(?:not available|unavailable|not included)",
        text,
        re.I,
    ):
        facts.pop("english_manual", None)
    if re.search(
        r"\b(?:not|no)\s+(?:diy|home|owner)[- ](?:serviceable|servicing|maintenance)",
        text,
        re.I,
    ):
        facts.pop("diy_serviceable", None)
    return facts


def classify_broad(listing, config):
    search = config["search"]
    requirements = search["requirements"]
    preferences = search.get("preferences", {})
    reject, unknown = [], []
    from .locations import area_status

    location_status = area_status(listing.location, search.get("allowed_locations", []))
    if location_status == "outside":
        reject.append(
            "Outside the configured search area: "
            + search.get("area_label", "configured towns")
        )
    elif location_status == "unknown":
        unknown.append("Exact location within the configured area is unconfirmed")
    if (
        listing.evidence.get("vehicle_type") == "ATV"
        or "/quads-atvs/" in urlsplit(listing.canonical_url).path
    ):
        reject.append("ATV/quad/side-by-side is not a motorcycle candidate")
    text = listing.title + "\n" + listing.description
    facts = advert_facts(text)
    from .research_sources import reviewed_reference_facts

    researched_facts = reviewed_reference_facts(listing)
    reference_conflicts = set()
    for field, fact in (
        listing.evidence.get("model_research", {}).get("facts", {}).items()
    ):
        if (
            field in researched_facts
            and researched_facts[field]["value"] != fact["value"]
        ):
            reference_conflicts.add(field)
        researched_facts[field] = fact
    for field in reference_conflicts:
        researched_facts.pop(field)
        unknown.append("Conflicting manufacturer specifications: " + field)
    conflicts = []
    for field, fact in researched_facts.items():
        if fact.get("kind") != "manufacturer_research" or not fact.get("source_url"):
            continue
        if field in facts and facts[field]["value"] != fact["value"]:
            conflicts.append(field)
            if field == "power_hp":
                # Either the seller's claim or the stock manufacturer's figure
                # below the minimum is sufficient to exclude this candidate.
                facts[field] = min(
                    (facts[field], fact), key=lambda record: record["value"]
                )
            else:
                facts.pop(field)
        else:
            facts[field] = fact
    unknown.extend("Advert/model research conflict: " + field for field in conflicts)
    minimum_power = requirements.get("min_power_hp")
    if minimum_power is not None:
        horsepower = facts.get("power_hp", {}).get("value")
        if horsepower is None:
            unknown.append(
                f"At least {minimum_power:g} hp mandatory; power unconfirmed"
            )
        elif horsepower < minimum_power:
            reject.append(
                f"Power {horsepower:g} hp below required {minimum_power:g} hp"
            )
    listing.power_status, listing.power_evidence = power(listing)
    # Explicit LAMS in either title or description always excludes in this search,
    # including adverts claiming conversion or contradicting themselves.
    cleaned = re.sub(
        r"\b(?:non[- ]lams|not\s+(?:(?:a|an|the)\s+)?lams)\b", "", text, flags=re.I
    )
    if (
        re.search(r"\blams\b|\blearner[- ]approved\b|\b35\s*kw\b", cleaned, re.I)
        or listing.power_status == "RESTRICTED"
    ):
        reject.append(
            "LAMS/restricted machine excluded, including converted or conflicting adverts"
        )
    elif listing.power_status != "UNRESTRICTED":
        unknown.append("Non-LAMS/full-power variant needs explicit confirmation")
    for value, limit, label in [
        (listing.model_year, search["min_year"], "Model year"),
        (listing.odometer_km, search["max_odometer_km"], "Odometer"),
        (
            listing.asking_price_nzd
            if listing.price_type in {"ASKING", "BUY_NOW"}
            else None,
            search["max_price_nzd"],
            "Fixed purchase price",
        ),
    ]:
        if value is None:
            unknown.append(label + " unknown")
        elif value < limit if label == "Model year" else value > limit:
            reject.append(label + " outside required range")
    cylinders = facts.get("cylinders", {}).get("value")
    if cylinders is None:
        unknown.append("Twin, triple or four-cylinder engine unconfirmed")
    elif cylinders not in requirements["cylinders"]:
        reject.append("Engine is not a twin, triple or four-cylinder")
    if requirements.get("abs"):
        abs_value = facts.get("abs", {}).get("value")
        if abs_value is False:
            reject.append("ABS absent or faulty")
        elif abs_value is None:
            unknown.append("ABS mandatory; fitment unconfirmed")
    for field, limit, label in [
        ("wet_weight_kg", requirements["max_wet_weight_kg"], "Wet weight"),
        ("seat_height_mm", requirements["max_seat_height_mm"], "Seat height"),
    ]:
        value = facts.get(field, {}).get("value")
        if value is None:
            unknown.append(label + " unconfirmed for this model/year/variant")
        elif value > limit:
            reject.append(label + " exceeds maximum")
    for field, label in [
        ("english_manual", "Obtainable English workshop documentation"),
        ("diy_serviceable", "DIY servicing suitability"),
    ]:
        if requirements.get(field) and facts.get(field, {}).get("value") is not True:
            unknown.append(label + " needs verification")
    if listing.listing_status != "ACTIVE":
        unknown.append("Availability not confirmed")
    assessments = []

    def preference(label, value, met):
        assessments.append(
            {
                "label": label,
                "status": "unknown"
                if value is None
                else "preferred"
                if met
                else "acceptable",
                "value": value,
            }
        )

    preference(
        f"{preferences['min_year']} or newer",
        listing.model_year,
        listing.model_year is not None
        and listing.model_year >= preferences["min_year"],
    )
    preference(
        f"Under {preferences['odometer_under_km']:,} km",
        listing.odometer_km,
        listing.odometer_km is not None
        and listing.odometer_km < preferences["odometer_under_km"],
    )
    for field, label, threshold, strict in [
        (
            "power_hp",
            f"At least {preferences['min_power_hp']:g} hp",
            preferences["min_power_hp"],
            False,
        ),
        (
            "wet_weight_kg",
            f"Wet weight under {preferences['wet_weight_under_kg']:g} kg",
            preferences["wet_weight_under_kg"],
            True,
        ),
        (
            "seat_height_mm",
            f"Seat height at most {preferences['max_seat_height_mm']:g} mm",
            preferences["max_seat_height_mm"],
            False,
        ),
    ]:
        value = facts.get(field, {}).get("value")
        met = value is not None and (
            value >= threshold
            if field == "power_hp"
            else value < threshold
            if strict
            else value <= threshold
        )
        preference(label, value, met)
    preference(
        "Factory screen / half or full fairing",
        facts.get("weather_protection", {}).get("value"),
        facts.get("weather_protection", {}).get("value") is True,
    )
    preference(
        "Model sold in USA",
        facts.get("us_market", {}).get("value"),
        facts.get("us_market", {}).get("value") is True,
    )
    location = listing.location
    preference(
        "Wellington / Lower North Island",
        location,
        bool(location)
        and any(
            region.lower() in location.lower() for region in search["preferred_regions"]
        ),
    )
    from .search_plan import screen

    screening = screen(listing, search, facts)
    if screening:
        reject.append(
            f"Operational plan screening (LLM estimate): {screening['rule']} has expected power below {requirements['min_power_hp']:g} hp. "
            + screening["reason"]
        )
        listing.evidence["operational_screen"] = screening
    else:
        listing.evidence.pop("operational_screen", None)
    listing.rejection_reasons = reject + unknown
    listing.classification = (
        "REJECTED" if reject else "REVIEW" if unknown else "ACCEPTED"
    )
    from .search_plan import preferred_model

    supported_power = facts.get("power_hp", {}).get("value")
    candidate_status = (
        "excluded"
        if listing.classification == "REJECTED"
        else "unassessed"
        if location_status != "inside"
        else "supported"
        if minimum_power is None
        or (supported_power is not None and supported_power >= minimum_power)
        else "promising"
        if preferred_model(listing, search)
        else "unassessed"
    )
    listing.evidence["suitability"] = {
        "candidate_status": candidate_status,
        "facts": facts,
        "preferences": assessments,
        "preference_matches": sum(
            item["status"] == "preferred" for item in assessments
        ),
        "evaluated_at": utc_now(),
        "note": "Advert claims and quoted manufacturer model research. Missing or conflicting specifications require review; advisory AI suggestions do not establish eligibility.",
    }
    return listing


def describe_search(search: dict) -> list[str]:
    """One configuration-derived criteria summary shared by dashboard clients."""
    broad = search.get("mode") == "all_models"
    names = (
        f"All models ({search['min_year']}+)"
        if broad
        else " / ".join(
            rule["model"]
            + (
                " (all years)"
                if rule.get("min_year") is None
                else f" ({rule['min_year']}+)"
            )
            for rule in search["models"]
        )
    )
    parts = [
        names,
        "No price ceiling"
        if search["max_price_nzd"] is None
        else f"Up to NZ${search['max_price_nzd']:,}",
        f"Maximum {search['max_odometer_km']:,} km",
        search.get("area_label", "Nationwide"),
    ]
    if broad:
        required = search["requirements"]
        preferred = search["preferences"]
        if required.get("min_power_hp") is not None:
            parts.append(f"At least {required['min_power_hp']:g} hp mandatory")
        if required["abs"]:
            parts.append("ABS mandatory")
        parts.extend(
            [
                "Non-LAMS only",
                f"Wet ≤{required['max_wet_weight_kg']:g} kg (prefer <{preferred['wet_weight_under_kg']:g} kg)",
                f"Seat ≤{required['max_seat_height_mm']:g} mm (prefer ≤{preferred['max_seat_height_mm']:g} mm)",
                f"Prefer {preferred['min_year']}+, <{preferred['odometer_under_km']:,} km, {preferred['min_power_hp']:g}+ hp",
            ]
        )
        if preferred.get("factory_weather_protection"):
            parts.append("Factory screen/fairing preferred")
        if preferred.get("us_market"):
            parts.append("US-market models preferred")
        if required["english_manual"]:
            parts.append("Obtainable English workshop documentation required")
        if required["diy_serviceable"]:
            parts.append("DIY servicing suitability required")
    return parts


def is_candidate(listing):
    """Positive selection; unknown discoveries are retained outside the shortlist."""
    return (
        listing.classification != "REJECTED"
        and listing.evidence.get("suitability", {}).get("candidate_status")
        != "unassessed"
    )
