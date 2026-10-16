import re

from .classification import power
from .normalization import model_name, utc_now
from .schema import Listing


def classify(listing: Listing, config: dict) -> Listing:
    if config["search"].get("mode") == "all_models":
        from .suitability import classify_broad

        return classify_broad(listing, config)
    listing.rejection_reasons = []
    reasons = listing.rejection_reasons
    listing.model = model_name(" ".join([listing.title, listing.model or ""]))
    models = {m["model"]: m for m in config["search"]["models"]}
    rule = models.get(listing.model)
    compact = re.sub(r"[^a-z0-9]", "", listing.title.lower())
    excluded = any(
        x in compact for x in ("z650", "zx6r", "ninja400", "ninja500", "gsx8s")
    )
    if not rule and not excluded and listing.model is None:
        if "ninja" in compact and listing.engine_cc in {649, 650}:
            rule = models.get("Ninja 650")
        elif "gsx8" in compact and listing.engine_cc in {776, 799, 800}:
            rule = models.get("GSX-8R")
    if not rule:
        reasons.append("Not a configured model (or conflicting/excluded family)")
    else:
        if listing.make and listing.make.lower() != rule["make"].lower():
            reasons.append("Make conflicts with model")
        listing.make = rule["make"]
    listing.power_status, listing.power_evidence = power(listing)
    listing.evidence["power_classification"] = {
        "source_url": listing.canonical_url,
        "verified_at": utc_now(),
        "reason": listing.power_evidence,
        "grade": "advert_claim",
    }
    if listing.power_status == "RESTRICTED":
        reasons.append("Confirmed restricted/LAMS power")
    if (
        listing.model_year is not None
        and rule
        and rule.get("min_year") is not None
        and listing.model_year < rule["min_year"]
    ):
        reasons.append("Model year below minimum")
    if (
        listing.asking_price_nzd is not None
        and listing.price_type in {"ASKING", "BUY_NOW"}
        and config["search"]["max_price_nzd"] is not None
        and listing.asking_price_nzd > config["search"]["max_price_nzd"]
    ):
        reasons.append("Price exceeds budget")
    if (
        listing.odometer_km is not None
        and listing.odometer_km > config["search"]["max_odometer_km"]
    ):
        reasons.append("Odometer exceeds maximum")
    expected_cc = {"Ninja 650": 649, "GSX-8R": 776}.get(listing.model)
    if (
        listing.engine_cc is not None
        and expected_cc
        and listing.engine_cc
        not in ({649, 650} if listing.model == "Ninja 650" else {776, 800})
    ):
        if listing.model != "GSX-8R" or listing.engine_cc != 799:
            reasons.append("Engine capacity conflicts with model")
    from .locations import area_status

    location_status = area_status(
        listing.location, config["search"].get("allowed_locations", [])
    )
    location_unknown = location_status == "unknown"
    if location_status == "outside":
        reasons.append("Outside the configured search area")
    if reasons:
        listing.classification = "REJECTED"
        return listing
    if listing.model == "GSX-8R" and listing.engine_cc == 799:
        reasons.append(
            "Advertised 799 cc conflicts with the GSX-8R's 776 cc engine; verify the advert"
        )
    if location_unknown:
        reasons.append("Exact location within the configured area is unconfirmed")
    if listing.model is None:
        reasons.append("Exact target model unconfirmed")
    if listing.model_year is None:
        reasons.append("Model year unknown")
    if listing.odometer_km is None:
        reasons.append("Odometer unknown")
    if listing.asking_price_nzd is None or listing.price_type not in {
        "ASKING",
        "BUY_NOW",
    }:
        reasons.append(
            "Fixed asking/buy-now price unknown; current bid is not a purchase price"
        )
    if listing.power_status == "UNKNOWN" and (
        not rule or rule.get("require_unrestricted", True)
    ):
        reasons.append(listing.power_evidence or "Power unknown")
    if listing.listing_status != "ACTIVE":
        reasons.append("Availability not confirmed")
    listing.classification = "REVIEW" if reasons else "ACCEPTED"
    return listing


def priority(listing: dict, config: dict) -> tuple:
    location = (listing.get("location") or "").lower()
    local = any(
        region.lower() in location for region in config["search"]["preferred_regions"]
    )
    # Display grouping only. No convenience weighting overrides eligibility or money.
    comparison = listing.get("changeover", {})
    cost = comparison.get("changeover_nzd")
    if cost is None:
        cost = (
            listing.get("asking_price_nzd")
            if listing.get("price_type") in {"ASKING", "BUY_NOW"}
            else None
        )
    return (
        listing["classification"] != "ACCEPTED",
        -listing.get("evidence", {})
        .get("suitability", {})
        .get("preference_matches", 0),
        cost if cost is not None else float("inf"),
        not (local and listing["preferred_dealer"]),
        not local,
    )


def current_criteria(data: dict, config: dict) -> dict:
    """Evaluate saved facts against current requirements without rewriting history."""
    listing = Listing.from_dict(
        {
            key: value
            for key, value in data.items()
            if key in Listing.__dataclass_fields__
        }
    )
    return {**data, **classify(listing, config).to_dict()}
