"""Conservative normalization; missing values remain unknown."""

import math
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, urlunsplit


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def date_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return parsed.astimezone(UTC).isoformat()


def money(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().upper()
    if not re.fullmatch(
        r"(?:NZ\$|NZD\s*|\$)?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", text
    ):
        return None
    try:
        amount = Decimal(re.sub(r"[^\d.]", "", text))
        # The schema uses whole NZD; don't silently round fractional advertised prices.
        return int(amount) if amount == int(amount) else None
    except (InvalidOperation, ValueError):
        return None


def mileage(value: object, unit: str = "km") -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().lower().replace(",", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(km|kms|kilometres|mi|miles)?", text)
    if not match:
        return None
    distance = float(match[1])
    actual_unit = match[2] or unit.lower()
    if actual_unit in {"mi", "miles", "smi"}:
        distance *= 1.609344
    elif actual_unit not in {"km", "kms", "kilometres", "kmt"}:
        return None
    return math.ceil(distance)


def safe_url(url: str, allowed_hosts: list[str] | tuple[str, ...]) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in {None, 80, 443}
        or parts.hostname.lower() not in {host.lower() for host in allowed_hosts}
        or any(ord(c) < 32 for c in url)
    ):
        raise ValueError(f"Unsafe or unconfigured URL: {url!r}")
    return url  # Exact original direct link is retained.


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", "")
    )


def model_name(value: str) -> str | None:
    text = re.sub(r"[^a-z0-9]", "", value.lower())
    if any(x in text for x in ("gsx8s", "zx6r", "z650", "ninja400", "ninja500")):
        return None
    if "gsx8r" in text:
        return "GSX-8R"
    if "ninja650" in text or re.search(r"ex650[a-z0-9]*", text):
        return "Ninja 650"
    return None
