from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Listing:
    source: str
    listing_id: str
    canonical_url: str
    title: str
    source_urls: list[str] = field(default_factory=list)
    description: str = ""
    make: str | None = None
    model: str | None = None
    model_year: int | None = None
    engine_cc: int | None = None
    asking_price_nzd: int | None = None
    price_type: str = "UNKNOWN"
    orc_nzd: int | None = None
    odometer_km: int | None = None
    location: str | None = None
    seller_name: str | None = None
    seller_type: str = "UNKNOWN"
    dealer_name: str | None = None
    preferred_dealer: bool = False
    trade_in_available: str = "UNKNOWN"
    power_status: str = "UNKNOWN"
    power_evidence: str | None = None
    classification: str = "REVIEW"
    rejection_reasons: list[str] = field(default_factory=list)
    listing_status: str = "ACTIVE"
    first_seen_utc: str | None = None
    last_seen_utc: str | None = None
    last_changed_utc: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    # Only exact, owner-verified identity can trigger a cross-source merge.
    verified_identity: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Listing":
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"Unknown listing fields: {sorted(unknown)}")
        result = cls(**data)
        for name, choices in {
            "price_type": {"ASKING", "BUY_NOW", "CURRENT_BID", "POA", "UNKNOWN"},
            "seller_type": {"DEALER", "PRIVATE", "UNKNOWN"},
            "trade_in_available": {"YES", "NO", "UNKNOWN"},
            "power_status": {"UNRESTRICTED", "RESTRICTED", "UNKNOWN"},
            "listing_status": {"ACTIVE", "ENDED", "UNKNOWN"},
        }.items():
            if getattr(result, name) not in choices:
                raise ValueError(f"Invalid {name}")
        for name in (
            "model_year",
            "engine_cc",
            "asking_price_nzd",
            "orc_nzd",
            "odometer_km",
        ):
            value = getattr(result, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or null")
        for name in ("source", "listing_id", "canonical_url", "title", "description"):
            if not isinstance(getattr(result, name), str):
                raise ValueError(f"{name} must be a string")
        if not result.source or not result.listing_id or not result.title:
            raise ValueError("source, listing_id and title are required")
        if not isinstance(result.evidence, dict) or not isinstance(
            result.source_urls, list
        ):
            raise ValueError("Invalid evidence or source_urls")
        return result
