"""Independent public dealer inventory discovery with evidence-bound extraction."""

import hashlib
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .filtering import classify
from .normalization import canonical_url, mileage, money, safe_url
from .parsers import ParseError, decorate, jsonld
from .schema import Listing

VEHICLE_LINK = re.compile(
    r"/bike/|/used_bikes/show/|/products/|/vehicle/|/shop/bikes-in-store/|/motorcycles-scooters/Used-Motorbikes-for-Sale/[^/]+/[^/]+/\d+",
    re.I,
)
MAKES = re.compile(
    r"\b(?:Honda|Yamaha|Suzuki|Kawasaki|Triumph|BMW|Aprilia|Ducati|KTM|Husqvarna|Moto Guzzi|Benelli|CFMoto|Royal Enfield|Harley[- ]Davidson)\b",
    re.I,
)


def visible_listing(node, url, source, options, *, title=None):
    text = node.get_text(" ", strip=True)
    if not title:
        heading = node.select_one(
            "h1, h2, h3, .car-title, .product-item__title, .products_title, .search-header, .product-title, .product-grid-item__title"
        )
        title = (
            heading.get_text(" ", strip=True)
            if heading
            else next(
                (
                    a.get_text(" ", strip=True)
                    for a in node.select("a[href]")
                    if MAKES.search(a.get_text(" ", strip=True))
                    and len(a.get_text(" ", strip=True)) < 200
                ),
                None,
            )
        )
    if not title or not MAKES.search(title):
        return None
    year = re.findall(r"\b(?:19|20)\d{2}\b", title)
    if not year:
        year = re.findall(r"\b((?:19|20)\d{2})\s+(?=" + MAKES.pattern + ")", text, re.I)
    years = set(year)
    model_year = int(next(iter(years))) if len(years) == 1 else None
    # A single current price or an explicit Now price; never use finance repayments,
    # auction bids, previous prices or unrelated recommended-product prices.
    price_node = node.select_one(
        '.price, .product-item__price-list, [itemprop="price"], .car-price'
    )
    price_text = price_node.get_text(" ", strip=True) if price_node else text
    now = re.search(r"\bNow\s*(\$\s*[\d,]+(?:\.\d{2})?)", price_text, re.I)
    amounts = set(re.findall(r"\$\s*[\d,]+(?:\.\d{2})?", price_text))
    amount = (
        money(now[1])
        if now
        else money(next(iter(amounts)))
        if len(amounts) == 1
        else None
    )
    auction = bool(
        re.search(
            r"\b(?:current bid|starting bid|online auction)\b",
            text,
            re.I,
        )
    )
    if auction or re.search(r"\b(?:weekly|per week|per month)\b", price_text, re.I):
        amount = None
    distances = {
        mileage(value)
        for value in re.findall(r"\b\d[\d,]*(?:\.\d+)?\s*km\b", text, re.I)
    }
    engines = {
        int(value.replace(",", ""))
        for value in re.findall(r"\b(\d[\d,]*)\s*cc\b", text, re.I)
    }
    listing = Listing(
        source,
        hashlib.sha256(canonical_url(url).encode()).hexdigest()[:20],
        url,
        title[:300],
        description=text[:24000],
        model_year=model_year,
        asking_price_nzd=amount,
        price_type="ASKING"
        if amount is not None
        else "CURRENT_BID"
        if auction
        else "UNKNOWN",
        odometer_km=next(iter(distances)) if len(distances) == 1 else None,
        engine_cc=next(iter(engines)) if len(engines) == 1 else None,
        listing_status="ENDED"
        if re.search(r"\b(?:sold out|sold|no longer available)\b", text, re.I)
        else "ACTIVE",
        make=MAKES.search(title)[0],
    )
    listing.evidence["web_discovery"] = {
        "source_url": url,
        "method": "visible inventory card",
        "note": "Seller advert claims; model specifications not inferred",
    }
    if re.search(r"\b(?:quad|atv|side[- ]by[- ]side)\b", text, re.I):
        listing.evidence["vehicle_type"] = "ATV"
    return decorate(listing, options)


def inventory(html, page_url, source, options):
    soup = BeautifulSoup(html, "html.parser")
    if any(
        marker in soup.get_text(" ", strip=True).lower()
        for marker in ["verify you are human", "access denied", "solve the captcha"]
    ):
        raise ParseError("Public inventory blocked or challenged")
    result = {}
    try:
        structured = jsonld(html, page_url, source, options)
    except ParseError:
        structured = []
    for listing in structured:
        if MAKES.search(listing.title):
            result[listing.canonical_url] = listing
    selectors = options.get(
        "card_selector",
        ".car-wrapper, .product-item, .product, .vehicle-card, .product-block, .product-grid-item, .content-product, article",
    )
    for node in soup.select(selectors):
        links = []
        for anchor in node.select("a[href]"):
            raw = urljoin(page_url, anchor["href"])
            if not VEHICLE_LINK.search(urlsplit(raw).path):
                continue
            try:
                url = safe_url(raw, options["allowed_hosts"])
            except ValueError:
                continue
            links.append(url)
        if not links:
            continue
        # Container must describe just one vehicle, never the whole stock page.
        urls = set(links)
        if len(urls) != 1:
            continue
        url = links[0]
        listing = visible_listing(node, url, source, options)
        if listing:
            result[url] = listing
    if not result:
        raise ParseError(
            "No recognized independent inventory cards; site may need a specific adapter, rendering, or manual review"
        )
    return list(result.values())


def collect_website(source, options, fetcher, config):
    result = {}
    for url in options["search_urls"]:
        current = url
        visited = set()
        for _ in range(options.get("max_pages", 2)):
            if current in visited:
                raise ParseError("Independent inventory repeated pagination")
            visited.add(current)
            html = fetcher.get(current, options["allowed_hosts"])
            for item in inventory(html, current, source, options):
                result[item.canonical_url] = item
            soup = BeautifulSoup(html, "html.parser")
            next_node = soup.select_one(
                'a[rel="next"], .pagination a.next, .pagination-next a, a.pagination__next'
            )
            if not next_node or not next_node.get("href"):
                break
            current = safe_url(
                urljoin(current, next_node["href"]), options["allowed_hosts"]
            )
    # Inventory card descriptions stay isolated from other stock when reading details.
    # Only use JSON-LD or a dedicated main product container, not the whole page body.
    candidates = sorted(
        result.values(),
        key=lambda x: (
            classify(x, config).classification == "REJECTED",
            -x.evidence.get("suitability", {}).get("preference_matches", 0),
        ),
    )
    details = 0
    for item in candidates:
        if item.classification == "REJECTED" or details >= options.get(
            "max_details", 2
        ):
            continue
        html = fetcher.get(item.canonical_url, options["allowed_hosts"])
        soup = BeautifulSoup(html, "html.parser")
        try:
            parsed_detail = jsonld(html, item.canonical_url, source, options)
        except ParseError:
            parsed_detail = []
        structured = [x for x in parsed_detail if x.canonical_url == item.canonical_url]
        if len(structured) == 1:
            detail = structured[0]
            for field in ["model_year", "odometer_km", "location", "engine_cc"]:
                if getattr(detail, field) is None:
                    setattr(detail, field, getattr(item, field))
            result[item.canonical_url] = detail
        else:
            # The existing inventory card supplies price/year/km; append only a
            # dedicated description element, never a whole page of recommended bikes.
            node = soup.select_one(
                '[itemprop="description"], .car-description, .vehicle-description, .product-description, .product-single__description, .product-meta__description'
            )
            if node:
                item.description += "\n" + node.get_text(" ", strip=True)[:16000]
        details += 1
    return list(result.values())
