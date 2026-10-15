"""Structured data parser and dealer parsers verified against public HTML.

Trade Me JSON-LD support is provisional until an actual supplied listing/search
is checked. Unsupported markup raises an error, rather than claiming zero bikes.
"""

import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .normalization import canonical_url, mileage, model_name, money, safe_url, utc_now
from .schema import Listing


class ParseError(ValueError):
    pass


def walk(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def integer(value: object) -> int | None:
    if isinstance(value, dict):
        value = value.get("value")
    match = re.fullmatch(r"\s*(\d+)\s*(?:cc)?\s*", str(value))
    return int(match[1]) if match else None


def decorate(listing: Listing, options: dict) -> Listing:
    if options.get("dealer_name"):
        listing.seller_type = "DEALER"
        listing.dealer_name = options["dealer_name"]
        listing.seller_name = options["dealer_name"]
        listing.preferred_dealer = bool(options.get("preferred_dealer", False))
        listing.location = listing.location or options.get("location")
        listing.evidence["dealer"] = {
            "source_url": options.get("dealer_evidence_url"),
            "verified_at": options.get("dealer_verified_at"),
            "grade": "configured_verified_identity",
        }
    listing.source_urls = list(
        dict.fromkeys([listing.canonical_url, *listing.source_urls])
    )
    listing.evidence["fetch"] = {
        "source_url": listing.canonical_url,
        "observed_at": utc_now(),
    }
    return listing


def jsonld(html: str, page_url: str, source: str, options: dict) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    objects = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            objects.extend(walk(json.loads(script.get_text())))
        except (json.JSONDecodeError, TypeError) as error:
            raise ParseError(f"Invalid JSON-LD at {page_url}: {error}") from error
    result = {}
    for obj in objects:
        kinds = obj.get("@type", [])
        if isinstance(kinds, str):
            kinds = [kinds]
        if not set(kinds).intersection({"Product", "Vehicle", "Motorcycle"}):
            continue
        title = obj.get("name")
        if not isinstance(title, str) or not title:
            continue
        raw_url = obj.get("url")
        if not raw_url:
            # A product on a search page without its own URL is unsafe to report.
            raise ParseError("Product lacks direct listing URL")
        url = safe_url(urljoin(page_url, raw_url), options["allowed_hosts"])
        identity = str(
            obj.get("productID")
            or obj.get("sku")
            or urlsplit(url).path.rstrip("/").split("/")[-1]
        )
        offers = obj.get("offers", {})
        if isinstance(offers, list):
            if len(offers) != 1:
                offers = {}  # Multiple variants/prices need review.
            else:
                offers = offers[0]
        if not isinstance(offers, dict):
            offers = {}
        is_fixed = (
            offers.get("@type") == "Offer" and offers.get("priceCurrency") == "NZD"
        )
        # Never map AggregateOffer.lowPrice or auction bid to asking price.
        amount = money(offers.get("price")) if is_fixed else None
        price_type = "ASKING" if amount is not None else "UNKNOWN"
        if obj.get("price_type") == "CURRENT_BID" or offers.get(
            "businessFunction", ""
        ).lower().endswith("auction"):
            price_type, amount = "CURRENT_BID", None
        brand = obj.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        odometer = obj.get("mileageFromOdometer")
        unit = "km"
        if isinstance(odometer, dict):
            unit, odometer = odometer.get("unitCode", ""), odometer.get("value")
        description = BeautifulSoup(
            str(obj.get("description") or ""), "html.parser"
        ).get_text(" ", strip=True)
        listing = Listing(
            source,
            identity,
            url,
            title,
            description=description,
            make=brand,
            model=obj.get("model"),
            model_year=integer(obj.get("vehicleModelDate") or obj.get("modelDate")),
            engine_cc=integer(obj.get("vehicleEngine", {}).get("engineDisplacement"))
            if isinstance(obj.get("vehicleEngine"), dict)
            else None,
            asking_price_nzd=amount,
            price_type=price_type,
            odometer_km=mileage(odometer, unit),
            listing_status="ENDED"
            if str(offers.get("availability", "")).endswith(("SoldOut", "Discontinued"))
            else "ACTIVE",
        )
        from .classification import power

        status, reasoning = power(listing)
        listing.evidence["parsed_power"] = {"status": status, "reason": reasoning}
        relevant = re.findall(
            r"[^.!?\n]*(?:lams|learner.approved|restricted|full.power(?:ed)?|35\s*kw)[^.!?\n]*",
            description,
            re.IGNORECASE,
        )
        listing.description = (
            description[:24000]
            if options.get("retain_description")
            else "; ".join(x.strip() for x in relevant)[:800]
        )
        references = obj.get("sameAs", [])
        if isinstance(references, str):
            references = [references]
        if isinstance(references, list):
            listing.source_urls.extend(
                safe_url(url, options["allowed_hosts"]) for url in references
            )
        result[(source, identity)] = decorate(listing, options)
    if not result:
        raise ParseError(
            f"No recognized listing schema at {page_url}; use saved-search alerts/manual JSON import or update parser"
        )
    return list(result.values())


def tss(html: str, page_url: str, source: str, options: dict) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".e-loop-item.type-motorcycles")
    if not cards:
        raise ParseError(
            "TSS stock cards missing; page structure changed or access failed"
        )
    result = []
    for card in cards:
        anchor = card.select_one("h3 a[href]")
        if not anchor:
            raise ParseError("TSS card title/direct link missing")
        url = safe_url(urljoin(page_url, anchor["href"]), options["allowed_hosts"])
        fields = {}
        for item in card.select(".elementor-icon-list-text"):
            key, sep, value = item.get_text(" ", strip=True).partition(":")
            if sep:
                fields[key.strip()] = value.strip()
        prices = [
            money(node.get_text(strip=True))
            for node in card.select(".jet-listing-dynamic-field__content")
        ]
        prices = [p for p in prices if p is not None]
        # Ambiguous old/new price markup is reviewed until a detail page resolves it.
        amount = prices[0] if len(prices) == 1 else None
        result.append(
            decorate(
                Listing(
                    source,
                    urlsplit(url).path.rstrip("/").split("/")[-1],
                    url,
                    anchor.get_text(" ", strip=True),
                    model_year=integer(fields.get("Year")),
                    engine_cc=integer(fields.get("Engine Size")),
                    odometer_km=mileage(fields.get("Kilometres")),
                    asking_price_nzd=amount,
                    price_type="ASKING" if amount is not None else "UNKNOWN",
                ),
                options,
            )
        )
    return result


def cyclespot(html: str, page_url: str, source: str, options: dict) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("#listCars .car-wrapper")
    if not cards:
        count = soup.select_one(".car-count-details")
        if count and re.search(r"Showing\s+0\s+vehicles available", count.get_text()):
            return []
        raise ParseError("Cyclespot stock cards/count missing; check page structure")
    count_node = soup.select_one(".car-count-details")
    if count_node:
        expected = re.search(
            r"Showing\s+(\d+)\s+vehicles available", count_node.get_text()
        )
        if not expected or int(expected[1]) != len(cards):
            raise ParseError(
                "Cyclespot inventory count exceeds/contradicts visible cards; narrow searches or verify pagination"
            )
    result = []
    for card in cards:
        info = card.select_one(".quick-view-wrapper[data-id][data-link][data-title]")
        specs = card.select_one(".other-spec")
        if not info or not specs:
            raise ParseError("Cyclespot card essential structure missing")
        url = safe_url(urljoin(page_url, info["data-link"]), options["allowed_hosts"])
        text = specs.get_text(" ", strip=True)
        odo = re.search(r"([\d,]+)km", text)
        engine = re.search(r"(\d+)cc", text)
        title = info["data-title"]
        year = re.search(r"\b(20\d{2}|19\d{2})\s*$", title)
        price_text = BeautifulSoup(info.get("data-price", ""), "html.parser").get_text(
            " ", strip=True
        )
        now = re.search(r"^Now\s+(\$[\d,]+)\s+Was\s+", price_text)
        amount = money(now[1] if now else price_text)
        result.append(
            decorate(
                Listing(
                    source,
                    str(info["data-id"]),
                    url,
                    title,
                    model_year=int(year[1]) if year else None,
                    engine_cc=int(engine[1]) if engine else None,
                    odometer_km=mileage(odo[1]) if odo else None,
                    asking_price_nzd=amount,
                    price_type="ASKING" if amount is not None else "UNKNOWN",
                ),
                options,
            )
        )
    return result


def parse(html: str, page_url: str, source: str, options: dict) -> list[Listing]:
    if any(
        marker in html.lower()
        for marker in (
            "verify you are human",
            "access denied",
            "cf-chl-",
            "solve the captcha",
        )
    ):
        raise ParseError(
            "Blocked/challenge page; use native saved searches or manual imports"
        )
    return {
        "jsonld": jsonld,
        "tss": tss,
        "cyclespot": cyclespot,
        "trademe": trademe_search,
        "trademe_detail": trademe_detail,
    }[options.get("parser", "jsonld")](html, page_url, source, options)


def trademe_search(
    html: str, page_url: str, source: str, options: dict
) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    count_node = soup.select_one("tm-search-header-result-count h3")
    count = (
        re.search(r"Showing\s+([\d,]+)\s+results", count_node.get_text())
        if count_node
        else None
    )
    if not count:
        raise ParseError(
            "Trade Me app shell or search structure changed; enable optional browser rendering"
        )
    expected = int(count[1].replace(",", ""))
    cards = soup.select("a.tm-tiered-search-card__link[href]")
    if expected == 0 and not cards:
        return []
    if not cards:
        raise ParseError("Trade Me count present but listing cards missing")
    result = []
    for card in cards:
        title_node = card.select_one(".tm-motors-search-card-title__title")
        price_node = card.select_one("tm-search-card-price")
        if not title_node or not price_node:
            raise ParseError("Trade Me essential card fields changed")
        url = safe_url(urljoin(page_url, card["href"]), options["allowed_hosts"])
        title = title_node.get_text(" ", strip=True)
        subtitle = card.select_one('[class*="search-card__subtitle"]')
        attributes = [
            x.get_text(" ", strip=True)
            for x in card.select(".tm-search-card-attributes__attribute-text")
        ]
        location = next(
            (
                x
                for x in attributes
                if "," in x and not re.search(r"\b(?:km|cc|hrs)\b", x)
            ),
            None,
        )
        odo = next((mileage(x) for x in attributes if re.search(r"\bkm$", x)), None)
        engine = next(
            (integer(x.replace(",", "")) for x in attributes if re.search(r"\bcc$", x)),
            None,
        )
        year = re.search(r"\b(20\d{2}|19\d{2})\b", title)
        price_text = price_node.get_text(" ", strip=True)
        fixed = re.search(
            r"(Asking price|Buy now|Or near offer)\s*(\$[\d,]+)",
            price_text,
            re.IGNORECASE,
        )
        amount = money(fixed[2]) if fixed else None
        kind = (
            "BUY_NOW"
            if fixed and fixed[1].lower() == "buy now"
            else "ASKING"
            if fixed
            else "CURRENT_BID"
            if re.search(r"reserve|current bid", price_text, re.IGNORECASE)
            else "POA"
            if re.search(r"POA|on application", price_text, re.IGNORECASE)
            else "UNKNOWN"
        )
        text = card.get_text(" ", strip=True)
        result.append(
            decorate(
                Listing(
                    source,
                    urlsplit(url).path.rstrip("/").split("/")[-1],
                    url,
                    title,
                    description=title
                    + ("; " + subtitle.get_text(" ", strip=True) if subtitle else ""),
                    model=model_name(
                        title
                        + (" " + subtitle.get_text(" ", strip=True) if subtitle else "")
                    ),
                    model_year=int(year[1]) if year else None,
                    odometer_km=odo,
                    engine_cc=engine,
                    location=location,
                    asking_price_nzd=amount,
                    price_type=kind,
                    orc_nzd=0 if "Includes on road costs" in text else None,
                    seller_type="PRIVATE"
                    if "Private seller" in text
                    else "DEALER"
                    if card.select_one(
                        "tm-seller-container .tm-motors-search-card__dealer-with-logo"
                    )
                    else "UNKNOWN",
                ),
                options,
            )
        )
    # Prevent incomplete search pages from becoming a successful zero/partial baseline.
    if len(result) < expected and not options.get("allow_partial", False):
        raise ParseError(
            f"Trade Me has {expected} results but only {len(result)} cards; narrow configured search or implement verified pagination"
        )
    for listing in result:
        listing.evidence["search_page"] = {"total": expected, "page_url": page_url}
    return result


def trademe_detail(
    html: str, page_url: str, source: str, options: dict
) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = jsonld(html, page_url, source, options)
    if len(candidates) != 1 or canonical_url(
        candidates[0].canonical_url
    ) != canonical_url(page_url):
        raise ParseError("Trade Me detail identity missing or ambiguous")
    listing = candidates[0]
    listing.canonical_url = (
        page_url  # Preserve original clicked URL, including its query.
    )
    listing.source_urls = [page_url]
    # JSON-LD may describe auction prices as Offer: require explicit UI price kind.
    prices = soup.select(".tm-motors-pricing-box__container")
    fixed = None
    for node in prices:
        label = node.select_one(".tm-motors-pricing-box__price-display")
        price = node.select_one(".tm-motors-pricing-box__price")
        if (
            label
            and price
            and label.get_text(" ", strip=True).lower()
            in {"asking price", "buy now", "or near offer"}
        ):
            fixed = (
                label.get_text(" ", strip=True),
                money(price.get_text(" ", strip=True)),
            )
            break
    if fixed and fixed[1] is not None:
        listing.price_type = "BUY_NOW" if fixed[0].lower() == "buy now" else "ASKING"
        listing.asking_price_nzd = fixed[1]
    else:
        listing.price_type, listing.asking_price_nzd = "UNKNOWN", None
    orc = soup.select_one(".tm-orc-description__value")
    listing.orc_nzd = 0 if orc and orc.get_text(strip=True) == "Included" else None
    for node in soup.select('script[type="application/ld+json"]'):
        for obj in walk(json.loads(node.get_text())):
            if obj.get("@type") not in {"Motorcycle", "Vehicle"}:
                continue
            seller = obj.get("offers", {}).get("offeredBy", {})
            if seller.get("@type") == "AutoDealer":
                listing.seller_type = "DEALER"
                listing.seller_name = listing.dealer_name = seller.get("name")
                address = seller.get("address", {})
                listing.location = (
                    ", ".join(
                        str(address[k])
                        for k in ["addressLocality", "addressRegion"]
                        if address.get(k)
                    )
                    or None
                )
            full_description = str(obj.get("description") or "")
            # Classify against the full description before retaining only concise evidence.
            from .classification import power

            listing.description = full_description
            listing.evidence.pop("parsed_power", None)
            status, evidence = power(listing)
            snippets = re.findall(
                r"[^.!?\n]*(?:lams|learner.approved|restricted|full.power(?:ed)?|35\s*kw)[^.!?\n]*",
                full_description,
                re.IGNORECASE,
            )
            listing.description = (
                full_description[:24000]
                if options.get("retain_description")
                else "; ".join(x.strip() for x in snippets)[:800]
            )
            listing.evidence["parsed_power"] = {"status": status, "reason": evidence}
    listing.preferred_dealer = listing.dealer_name in {
        "TSS Motorcycles",
        "Cyclespot Wellington",
    }
    listing.evidence["dealer"] = {
        "source_url": page_url,
        "verified_at": utc_now(),
        "grade": "structured_advert_identity",
    }
    # A generic Trade Me trade-in enquiry button is not a verified dealer allowance.
    return [listing]
