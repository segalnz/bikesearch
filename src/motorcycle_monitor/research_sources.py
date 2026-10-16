"""Verified document locations, not a model whitelist or guessed specifications.

Entries only provide acquisition leads for the stated year. Every specification
still has to be read from the document and quote-checked. Keep archived sources
here because public indexes frequently omit manufacturer archives.
"""

import re

KAWASAKI = {
    2017: "https://www.kawasaki.ie/2017-brochures/ninja_2017_brochure-web-2.pdf",
    2018: "https://kawasaki.ie/brochures/supersport-sport-ebrochure-web.pdf",
    2020: "https://storage.kawasaki.eu/repository/be/nl-BE/Brochures_2020/Ninja_Supersport_brochure_2020_PDF_3.pdf",
    2024: "https://www.kawasaki.eu/content/dam/europe/master/pdf-files/brochures/Kawasaki_Brochure_FullLine_2024.pdf",
}
HONDA = {
    (
        "cbr650r",
        2019,
    ): "https://hondanews.eu/eu/lv/motorcycles/media/pressreleases/155724/2019-honda-cbr650r",
    (
        "cbr650r",
        2021,
    ): "https://hondanews.eu/gb/en/motorcycles/media/pressreleases/309341/2021-honda-cbr650r",
    (
        "cb650r",
        2021,
    ): "https://hondanews.eu/gb/en/motorcycles/media/pressreleases/309371/2021-honda-cb650r",
    (
        "cb500f",
        2019,
    ): "https://hondanews.eu/gb/en/motorcycles/media/pressreleases/156265/2019-honda-cb500f",
}


def document_urls(listing):
    title = " ".join(filter(None, [listing.make, listing.model, listing.title])).lower()
    urls = []
    if "kawasaki" in title and listing.model_year in KAWASAKI:
        if listing.model_year == 2024 or "ninja" in title:
            urls.append(KAWASAKI[listing.model_year])
    if "honda" in title:
        # Match formatted names such as "Honda CBR 650 R" without accepting CB650R as CBR650R.
        compact = re.sub(r"[^a-z0-9]", "", title)
        for (model, year), url in HONDA.items():
            if listing.model_year == year and model in compact and url not in urls:
                urls.append(url)
    if "yamaha" in title:
        models = {
            "mt07": "MT07",
            "mt09": "MT09",
            "xsr700": "XSR700",
            "xsr900": "XS850" if listing.model_year <= 2021 else "XSR900",
            "yzfr7": "YZF700",
            "tracer700": "MT07TR",
            "tracer900": "MT09TRA",
        }
        compact = re.sub(r"[^a-z0-9]", "", title)
        for alias, code in models.items():
            if alias in compact:
                # Stable manufacturer factsheet convention. Failed URLs are
                # acquisition failures, never evidence for a specification.
                year = listing.model_year
                urls.append(
                    f"https://cdn2.yamaha-motor.eu/prod/product-assets/{year}/{code}/Factsheets/{year}-{code}_en.pdf"
                )
    return urls


def indexed_claims(listing, documents):
    """Human-checked table associations, still verified against fetched documents.

    Multi-model brochure tables are hard for an extraction model to quote reliably.
    These reviewed associations avoid confusing the adjacent ZX-6R/400 columns or
    copying rounded metric PS as hp. No claim survives a changed/missing document.
    """
    title = re.sub(
        r"[^a-z0-9]",
        "",
        " ".join(filter(None, [listing.make, listing.model, listing.title])).lower(),
    )
    association = None
    if "kawasaki" in title and "ninja650" in title and listing.model_year in KAWASAKI:
        association = (KAWASAKI[listing.model_year], r"Ninja\s+650", r"50\.2\s*kW")
    elif "honda" in title and "cb500f" in title and listing.model_year == 2019:
        association = (HONDA[("cb500f", 2019)], r"CB500F", r"35\s*kW")
    if association is None:
        return []
    url, model_pattern, power_pattern = association
    claims = []
    for index, doc in enumerate(documents):
        if doc["url"] != url:
            continue
        model = re.search(model_pattern, doc["text"], re.I)
        power = re.search(power_pattern, doc["text"], re.I)
        year = re.search(str(listing.model_year), doc["text"])
        if model and power and year:
            claims.append(
                {
                    "field": "power_hp",
                    "value": 1,
                    "source": index,
                    "model_quote": model[0],
                    "year_quote": year[0],
                    "quotation": power[0],
                }
            )
    return claims


# Human-reviewed, exact-model-year manufacturer facts. These are specification
# evidence, separate from the LLM's operational estimates. Keep the source and
# quotation with every value; do not extrapolate across model generations.
REVIEWED_SEAT_HEIGHTS = (
    (
        "Kawasaki",
        ("Ninja ZX-6R", "ZX-6R"),
        2026,
        830,
        "https://www.kawasaki.com.au/en-au/motorcycle/ninja/supersport/ninja-zx-6r/2026-ninja-zx-6r",
        "Seat Height 830 mm",
    ),
    (
        "Yamaha",
        ("XSR900",),
        2020,
        830,
        "https://cdn2.yamaha-motor.eu/prod/product-assets/2020/XS850/Factsheets/2020-XS850_en-GB.pdf",
        "Seat height 830 mm",
    ),
)


def reviewed_reference_facts(listing):
    from .search_plan import model_matches

    for make, aliases, year, height, url, quotation in REVIEWED_SEAT_HEIGHTS:
        if listing.model_year == year and any(
            model_matches(listing, make, alias) for alias in aliases
        ):
            text = listing.title + "\n" + listing.description
            if re.search(
                r"\b(?:lowered|lowering)\s+(?:seat|suspension|\d+\s*mm)|\b(?:seat|suspension)\s+(?:height\s+)?(?:lowered|lowering)|\blow[- ]seat\b|\blowering (?:kit|links)\b",
                text,
                re.I,
            ):
                return {}
            return {
                "seat_height_mm": {
                    "value": height,
                    "quotation": quotation,
                    "source_url": url,
                    "model_quote": make + " " + aliases[0],
                    "year_quote": str(year),
                    "kind": "manufacturer_research",
                    "checked_at": "2026-10-16",
                    "reviewed_reference": True,
                }
            }
    return {}
