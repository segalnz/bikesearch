"""Optional indexed-web-search adapters; direct inventories need no search API."""

import ipaddress
import socket
import time
from urllib.parse import urlsplit

import httpx

from .normalization import safe_url
from .parsers import ParseError, jsonld
from .secrets import credential
from .web_discovery import inventory


class SearchUnavailable(RuntimeError):
    pass


class WebSearch:
    def __init__(self, options: dict, client: httpx.Client | None = None):
        self.options = options
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)
        self.owned = client is None

    def close(self) -> None:
        if self.owned:
            self.client.close()

    def search(self, query: str) -> list[str]:
        provider = self.options["provider"]
        try:
            if provider == "brave":
                key = credential("BRAVE_SEARCH_API_KEY", self.options["api_key_file"])
                response = self.client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "country": "NZ", "count": 8},
                    headers={"X-Subscription-Token": key},
                )
            elif provider == "tavily":
                key = credential("TAVILY_API_KEY", self.options["api_key_file"])
                response = self.client.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": "Bearer " + key},
                    json={
                        "query": query,
                        "max_results": 8,
                        "search_depth": "basic",
                        "include_answer": False,
                    },
                )
            else:
                raise ValueError("Unknown search provider")
            if response.status_code != 200 or len(response.content) > 1_000_000:
                raise ValueError("Search provider unavailable")
            payload = response.json()
            results = (
                payload.get("web", {}).get("results", [])
                if provider == "brave"
                else payload.get("results", [])
            )
            if not isinstance(results, list):
                raise ValueError("Invalid search response")
            return [
                item["url"]
                for item in results[:8]
                if isinstance(item, dict) and isinstance(item.get("url"), str)
            ]
        except (OSError, ValueError, httpx.HTTPError):
            raise SearchUnavailable(
                "Indexed search unavailable; direct dealer collection continues. Check search provider settings/credential."
            ) from None


def public_nz_url(url: str) -> list[str]:
    """Untrusted discovery can only introduce public NZ hosts, never LAN targets."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if not host.endswith(".nz") or host.endswith(".local.nz"):
        raise ValueError("Discovery URL is not a NZ public host")
    safe_url(url, [host])
    addresses = socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(
        not ipaddress.ip_address(row[4][0]).is_global for row in addresses
    ):
        raise ValueError("Discovery URL resolves to a non-public address")
    return [host]


def collect_indexed(source: str, options: dict, fetcher, config: dict) -> list:
    search = WebSearch(options)
    result = {}
    visited = set()
    try:
        for query in options["queries"][: options.get("max_queries", 4)]:
            # Provider requests share the same global acquisition budget and pacing.
            if fetcher.requests >= config["collector"]["max_requests"]:
                raise SearchUnavailable("Acquisition request budget exhausted")
            delay = config["collector"]["request_interval_seconds"] - (
                time.monotonic() - fetcher.last_request
            )
            if delay > 0:
                time.sleep(delay)
            fetcher.requests += 1
            fetcher.last_request = time.monotonic()
            urls = search.search(
                query.format(
                    price=config["search"]["max_price_nzd"],
                    year=config["search"]["min_year"],
                )
            )
            for url in urls:
                if url in visited or len(visited) >= options.get("max_documents", 12):
                    continue
                visited.add(url)
                try:
                    hosts = public_nz_url(url)
                    html = fetcher.get(url, hosts)
                    discovered = {
                        **options,
                        "allowed_hosts": hosts,
                        "retain_description": True,
                    }
                    try:
                        listings = inventory(html, url, source, discovered)
                    except ParseError:
                        listings = jsonld(html, url, source, discovered)
                    for listing in listings:
                        # Discovery is partial; claims and availability remain source evidence.
                        listing.evidence["indexed_discovery"] = {
                            "query": query,
                            "source_url": url,
                            "provider": options["provider"],
                        }
                        result[listing.canonical_url] = listing
                except (OSError, ValueError, RuntimeError):
                    # Blocked/unrecognized documents do not stop independent sites.
                    continue
    finally:
        search.close()
    if not result:
        raise SearchUnavailable(
            "Indexed discovery found no parseable adverts; results may need manual review. This is not evidence of no qualifying bikes."
        )
    return list(result.values())
