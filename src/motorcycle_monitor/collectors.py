"""Serial public HTTP acquisition, bounded and paced, without account access."""

import hashlib
import json
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from .filtering import classify
from .normalization import safe_url
from .parsers import ParseError, parse


class CollectionError(RuntimeError):
    pass


class Fetcher:
    def __init__(
        self,
        config: dict,
        cache_dir: Path | None = None,
        client: httpx.Client | None = None,
    ):
        self.config = config
        self.cache_dir = cache_dir
        self.client = client or httpx.Client(
            timeout=config["request_timeout_seconds"],
            follow_redirects=False,
            headers={
                "User-Agent": "MotorcycleMonitor/0.1 (personal purchase research)"
            },
        )
        self.requests = 0
        self.last_request = 0.0
        self.cache: dict[str, str] = {}
        self.blocked_hosts: set[str] = set()

    def close(self) -> None:
        self.client.close()

    def get(self, url: str, hosts: list[str], *, data: dict | None = None) -> str:
        safe_url(url, hosts)
        if urlsplit(url).hostname in self.blocked_hosts:
            raise CollectionError(
                "Source is challenged/rate-limited for this scan; moving to other sources"
            )
        cache_key = url + (json.dumps(data, sort_keys=True) if data is not None else "")
        if cache_key in self.cache:
            return self.cache[cache_key]
        cache_file = (
            self.cache_dir / (hashlib.sha256(cache_key.encode()).hexdigest() + ".html")
            if self.cache_dir
            else None
        )
        if (
            cache_file
            and cache_file.exists()
            and time.time() - cache_file.stat().st_mtime < self.config["cache_seconds"]
        ):
            return cache_file.read_text()
        current = url
        redirects = 0
        for attempt in range(self.config["max_retries"] + 1):
            while True:
                if self.requests >= self.config["max_requests"]:
                    raise CollectionError(
                        "Request budget exhausted; narrow searches or increase max_requests"
                    )
                delay = self.config["request_interval_seconds"] - (
                    time.monotonic() - self.last_request
                )
                if delay > 0:
                    time.sleep(delay)
                self.last_request = time.monotonic()
                self.requests += 1
                try:
                    # No cookie/session identity persists between public page requests.
                    self.client.cookies.clear()
                    response = (
                        self.client.get(current)
                        if data is None
                        else self.client.post(current, data=data)
                    )
                except httpx.TransportError as error:
                    if attempt == self.config["max_retries"]:
                        raise CollectionError(
                            f"HTTP transport failure: {url}: {error}"
                        ) from error
                    break
                if response.status_code in {403, 429}:
                    self.blocked_hosts.add(urlsplit(current).hostname)
                    raise CollectionError(
                        f"HTTP {response.status_code}: blocked {current}; stop this source; use native saved searches/manual import"
                    )
                if response.is_redirect:
                    redirects += 1
                    if redirects > 5 or not response.headers.get("location"):
                        raise CollectionError("Invalid or excessive redirects")
                    current = safe_url(
                        urljoin(current, response.headers["location"]), hosts
                    )
                    continue
                if response.status_code >= 500 and attempt < self.config["max_retries"]:
                    break
                if response.status_code != 200:
                    raise CollectionError(f"HTTP {response.status_code} for {current}")
                content_kind = "text/html" if data is None else "application/json"
                media_type = response.headers.get("content-type", "")
                is_rss = (
                    self.config.get("allow_research_rss", False)
                    and urlsplit(current).hostname == "www.bing.com"
                    and any(
                        kind in media_type
                        for kind in (
                            "application/rss+xml",
                            "text/xml",
                            "application/xml",
                        )
                    )
                )
                is_pdf = (
                    self.config.get("allow_research_pdf", False)
                    and "application/pdf" in media_type
                )
                if content_kind not in media_type and not is_rss and not is_pdf:
                    raise CollectionError(f"Unexpected content type for {current}")
                if len(response.content) > (15_000_000 if is_pdf else 5_000_000):
                    raise CollectionError("Document exceeds acquisition size limit")
                if is_pdf:
                    from pypdf import PdfReader
                    from pypdf.errors import PdfReadError

                    try:
                        document = PdfReader(BytesIO(response.content))
                        if document.is_encrypted or len(document.pages) > 100:
                            raise CollectionError(
                                "Research PDF exceeds document limits"
                            )
                        html = "\n".join(
                            page.extract_text(extraction_mode="layout")
                            for page in document.pages
                        )
                    except PdfReadError:
                        raise CollectionError("Unreadable research PDF") from None
                else:
                    html = response.text
                if any(
                    marker in html.lower()
                    for marker in (
                        "verify you are human",
                        "solve the captcha",
                        "cf-chl-",
                    )
                ):
                    self.blocked_hosts.add(urlsplit(current).hostname)
                    raise CollectionError(
                        "Public page presented a challenge; moving to other sources"
                    )
                self.cache[cache_key] = html
                # Cache only acquisition; parser failures are still explicit on each run.
                if cache_file:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(html)
                return html
            time.sleep(2**attempt)
        raise CollectionError(f"Unable to fetch {url}")


def collect(source: str, options: dict, fetcher: Fetcher, config: dict) -> list:
    if options.get("parser") == "indexed_search":
        from .search import collect_indexed

        return collect_indexed(source, options, fetcher, config)
    if options.get("parser") == "website":
        from .web_discovery import collect_website

        return collect_website(source, options, fetcher, config)
    if options.get("parser") == "trademe" and options.get("allow_partial"):
        return collect_broad_trademe(source, options, fetcher, config)
    urls = options.get("search_urls", [])
    if not urls:
        raise CollectionError(
            f"{source}: enabled source has no manually validated search URLs"
        )
    if options.get("parser") == "tss":
        from .dealers import collect_tss

        return collect_tss(source, options, fetcher, config)
    listings = {}
    for url in urls:
        html = fetcher.get(url, options["allowed_hosts"])
        try:
            parsed = parse(html, url, source, options)
        except ParseError:
            if not config["collector"]["enable_browser_fallback"] or options.get(
                "parser"
            ) not in {"trademe", "trademe_detail"}:
                raise
            # Browser enhancement is only for a successfully fetched app shell.
            # Never turn an HTTP block or explicit challenge into browser retries.
            if any(
                x in html.lower()
                for x in ("access denied", "verify you are human", "cf-chl-")
            ):
                raise
            from .browser import render

            if fetcher.requests >= config["collector"]["max_requests"]:
                raise CollectionError("Request budget exhausted before browser render")
            delay = config["collector"]["request_interval_seconds"] - (
                time.monotonic() - fetcher.last_request
            )
            if delay > 0:
                time.sleep(delay)
            fetcher.last_request = time.monotonic()
            fetcher.requests += 1
            html = render(url, options["allowed_hosts"], config["collector"])
            parsed = parse(html, url, source, options)
        # Detail links are followed only for plausible accepted/review candidates.
        for listing in parsed:
            classify(listing, config)
            if listing.classification != "REJECTED" and options.get("detail_parser"):
                detail = fetcher.get(listing.canonical_url, options["allowed_hosts"])
                detail_options = {**options, "parser": options["detail_parser"]}
                try:
                    candidates = parse(
                        detail, listing.canonical_url, source, detail_options
                    )
                except ParseError:
                    if not config["collector"]["enable_browser_fallback"] or any(
                        x in detail.lower()
                        for x in ("access denied", "verify you are human", "cf-chl-")
                    ):
                        raise
                    from .browser import render

                    if fetcher.requests >= config["collector"]["max_requests"]:
                        raise CollectionError(
                            "Request budget exhausted before detail rendering"
                        )
                    delay = config["collector"]["request_interval_seconds"] - (
                        time.monotonic() - fetcher.last_request
                    )
                    if delay > 0:
                        time.sleep(delay)
                    fetcher.last_request = time.monotonic()
                    fetcher.requests += 1
                    detail = render(
                        listing.canonical_url,
                        options["allowed_hosts"],
                        config["collector"],
                    )
                    candidates = parse(
                        detail, listing.canonical_url, source, detail_options
                    )
                if (
                    len(candidates) != 1
                    or candidates[0].canonical_url != listing.canonical_url
                ):
                    raise CollectionError("Detail page identity ambiguous")
                detail_listing = candidates[0]
                for field in (
                    "location",
                    "seller_name",
                    "dealer_name",
                    "model_year",
                    "odometer_km",
                    "model",
                ):
                    if getattr(detail_listing, field) is None:
                        setattr(detail_listing, field, getattr(listing, field))
                if detail_listing.seller_type == "UNKNOWN":
                    detail_listing.seller_type = listing.seller_type
                listing = detail_listing
            listings[(source, listing.listing_id)] = listing
        soup = BeautifulSoup(html, "html.parser")
        if soup.select_one('a[rel="next"]') or (
            soup.select_one("#pages")
            and int(soup.select_one("#pages").get("value", "1")) > 1
        ):
            raise CollectionError(
                "Search is paginated; configure all validated page URLs or narrower searches (partial results not committed)"
            )
    return list(listings.values())


def public_page(url, source, options, fetcher, config):
    html = fetcher.get(url, options["allowed_hosts"])
    try:
        return html, parse(html, url, source, options)
    except ParseError:
        if not config["collector"]["enable_browser_fallback"] or any(
            word in html.lower()
            for word in ["access denied", "verify you are human", "cf-chl-"]
        ):
            raise
        from .browser import render

        if fetcher.requests >= config["collector"]["max_requests"]:
            raise CollectionError("Request budget exhausted before browser rendering")
        delay = config["collector"]["request_interval_seconds"] - (
            time.monotonic() - fetcher.last_request
        )
        if delay > 0:
            time.sleep(delay)
        fetcher.requests += 1
        fetcher.last_request = time.monotonic()
        html = render(url, options["allowed_hosts"], config["collector"])
        return html, parse(html, url, source, options)


def criteria_search_url(url: str, search: dict) -> str:
    """Keep verified public filter parameters derived from the current policy."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update(
        price_max=str(search["max_price_nzd"]),
        year_min=str(search["min_year"]),
        odometer_max=str(search["max_odometer_km"]),
    )
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def collect_broad_trademe(source, options, fetcher, config):
    """Bounded discovery, explicitly partial: never evidence that a bike vanished."""
    listings = {}
    cursors = []
    for configured_url in options["search_urls"]:
        start = criteria_search_url(configured_url, config["search"])
        cursor_file = (
            fetcher.cache_dir
            / ("discovery-" + hashlib.sha256(start.encode()).hexdigest() + ".json")
            if fetcher.cache_dir
            else None
        )
        cursor = 2
        if cursor_file and cursor_file.exists():
            try:
                cursor = max(2, int(json.loads(cursor_file.read_text())["page"]))
            except (ValueError, KeyError, TypeError):
                pass
        current = start
        for index in range(options.get("max_pages", 6)):
            html, parsed = public_page(current, source, options, fetcher, config)
            for listing in parsed:
                listings[listing.listing_id] = listing
            soup = BeautifulSoup(html, "html.parser")
            next_link = next(
                (
                    a
                    for a in soup.select("a[href]")
                    if a.get_text(" ", strip=True).lower() == "next"
                ),
                None,
            )
            if not next_link:
                cursor = 2
                break
            next_url = safe_url(
                urljoin(current, next_link["href"]), options["allowed_hosts"]
            )
            if next_url == current:
                raise CollectionError("Repeated pagination URL")
            if index == 0:
                pages = [
                    int(value)
                    for a in soup.select("a[href]")
                    for key, value in parse_qsl(urlsplit(a["href"]).query)
                    if key == "page" and value.isdigit()
                ]
                if pages and cursor > max(pages):
                    cursor = 2
                parts = urlsplit(next_url)
                query = dict(parse_qsl(parts.query))
                query["page"] = str(cursor)
                next_url = urlunsplit(
                    (parts.scheme, parts.netloc, parts.path, urlencode(query), "")
                )
            else:
                cursor = int(
                    dict(parse_qsl(urlsplit(next_url).query)).get("page", cursor + 1)
                )
            current = next_url
        if cursor_file:
            cursors.append((cursor_file, cursor))
    # Fetch the most promising adverts first; this orders work, never excludes bikes.
    candidates = [classify(item, config) for item in listings.values()]
    candidates.sort(
        key=lambda x: (
            x.classification == "REJECTED",
            x.power_status != "UNRESTRICTED",
            not any(
                region.lower() in (x.location or "").lower()
                for region in config["search"]["preferred_regions"]
            ),
            -(x.engine_cc or 0),
        )
    )
    detailed = 0
    for listing in candidates:
        if listing.classification == "REJECTED" or detailed >= options.get(
            "max_details", 12
        ):
            continue
        _, detail = public_page(
            listing.canonical_url,
            source,
            {**options, "parser": options["detail_parser"]},
            fetcher,
            config,
        )
        if len(detail) != 1 or detail[0].listing_id != listing.listing_id:
            raise CollectionError("Detail identity mismatch")
        item = detail[0]
        for field in ["model_year", "location", "odometer_km", "engine_cc"]:
            if getattr(item, field) is None:
                setattr(item, field, getattr(listing, field))
        item.evidence["search_page"] = listing.evidence["search_page"]
        listings[listing.listing_id] = item
        detailed += 1
    for cursor_file, cursor in cursors:
        cursor_file.parent.mkdir(parents=True, exist_ok=True)
        cursor_file.write_text(json.dumps({"page": cursor}))
    return list(listings.values())
