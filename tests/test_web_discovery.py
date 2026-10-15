import socket

import httpx
import pytest

from motorcycle_monitor.collectors import CollectionError, Fetcher
from motorcycle_monitor.search import WebSearch, public_nz_url
from motorcycle_monitor.web_discovery import inventory


def test_inventory_isolated_cards_and_no_added_date_as_model_year():
    html = """<div class="product"><h3>Honda CB650F</h3><p>Added Dec 2024</p><p>Price: $9,995</p><a href="/bike/honda/cb650/1">View</a></div>
    <div class="product"><h3>2020 Yamaha MT-09</h3><p>ABS 12,000km 847cc</p><p>Now $11,995 Was $12,995</p><a href="/bike/yamaha/mt09/2">View</a></div>"""
    result = inventory(
        html, "https://dealer.example", "dealer", {"allowed_hosts": ["dealer.example"]}
    )
    assert len(result) == 2
    assert result[0].model_year is None
    assert result[0].asking_price_nzd == 9995
    assert result[1].asking_price_nzd == 11995
    assert result[1].odometer_km == 12000
    assert "Yamaha" not in result[0].description


def test_auction_and_empty_or_blocked_pages_are_not_matches():
    html = '<article><h2>2020 Suzuki SV650</h2><p>Current Bid $8,000</p><a href="/bike/suzuki/sv650/1">View</a></article>'
    result = inventory(
        html, "https://dealer.example", "dealer", {"allowed_hosts": ["dealer.example"]}
    )
    assert result[0].asking_price_nzd is None
    for page in ["<html>No inventory schema</html>", "Verify you are human"]:
        with pytest.raises(ValueError):
            inventory(
                page,
                "https://dealer.example",
                "dealer",
                {"allowed_hosts": ["dealer.example"]},
            )


def test_challenged_host_stops_for_remaining_scan(config):
    calls = []
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (calls.append(request), httpx.Response(429))[1]
        )
    )
    fetcher = Fetcher(config["collector"], client=client)
    with pytest.raises(CollectionError):
        fetcher.get("https://www.trademe.co.nz/search", ["www.trademe.co.nz"])
    with pytest.raises(CollectionError, match="moving to other sources"):
        fetcher.get("https://www.trademe.co.nz/another", ["www.trademe.co.nz"])
    assert len(calls) == 1
    fetcher.close()


def test_indexed_discovery_rejects_private_and_non_nz_urls(monkeypatch):
    for url in ["http://127.0.0.1/", "http://169.254.169.254/", "https://example.com/"]:
        with pytest.raises(ValueError):
            public_nz_url(url)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("192.168.5.72", 443))],
    )
    with pytest.raises(ValueError):
        public_nz_url("https://dealer.co.nz/bike")


@pytest.mark.parametrize("provider", ["brave", "tavily"])
def test_search_provider_contracts_do_not_expose_key(tmp_path, provider):
    path = tmp_path / "search.token"
    path.write_text("synthetic-key")

    def response(request):
        if provider == "brave":
            assert request.headers["X-Subscription-Token"] == "synthetic-key"
            return httpx.Response(
                200, json={"web": {"results": [{"url": "https://dealer.co.nz/bike"}]}}
            )
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        return httpx.Response(
            200, json={"results": [{"url": "https://dealer.co.nz/bike"}]}
        )

    search = WebSearch(
        {"provider": provider, "api_key_file": str(path)},
        httpx.Client(transport=httpx.MockTransport(response)),
    )
    assert search.search("used motorcycles NZ") == ["https://dealer.co.nz/bike"]
