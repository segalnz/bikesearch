"""Conservative town matching against the configured geographic boundary."""

import re
import unicodedata


def normalize(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def area_status(location, allowed):
    """Return inside, outside or unknown; a regional suffix cannot admit a town."""
    if not allowed:
        return "inside"
    regions = {"manawatu", "manawatu whanganui", "wairarapa", "wellington region"}
    normalized = normalize(location or "")
    if not normalized or normalized in regions:
        return "unknown"
    parts = [normalize(part) for part in (location or "").split(",")]
    towns = (
        parts[:-1]
        if len(parts) > 1 and parts[-1] in regions | {"wellington"}
        else parts
    )
    if any(
        re.search(r"(?<!\w)" + re.escape(normalize(place)) + r"(?!\w)", town)
        for place in allowed
        for town in towns
    ):
        return "inside"
    if len(parts) > 1 and parts[-1] in regions | {"wellington"}:
        return "unknown"
    return "outside"
