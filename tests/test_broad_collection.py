import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from test_suitability import machine

from motorcycle_monitor import collectors
from motorcycle_monitor.filtering import classify
from motorcycle_monitor.service import scan
from motorcycle_monitor.storage import Store


def test_broad_pages_rotate_without_turning_absence_into_evidence(
    tmp_path, monkeypatch, broad_config
):
    visited = []

    def page(url, source, options, fetcher, config):
        number = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
        visited.append(number)
        listing = machine(listing_id=str(number))
        listing.evidence["search_page"] = {"total": 100}
        return f'<a href="?page={number + 1}">Next</a><a href="?page=10">10</a>', [
            listing
        ]

    monkeypatch.setattr(collectors, "public_page", page)
    options = {
        "search_urls": ["https://www.trademe.co.nz/a/search"],
        "allowed_hosts": ["www.trademe.co.nz"],
        "max_pages": 3,
        "max_details": 0,
    }
    fetcher = SimpleNamespace(cache_dir=tmp_path)
    assert (
        len(collectors.collect_broad_trademe("trademe", options, fetcher, broad_config))
        == 3
    )
    assert visited == [1, 2, 3]
    visited.clear()
    collectors.collect_broad_trademe("trademe", options, fetcher, broad_config)
    assert visited == [1, 4, 5]


def test_partial_scan_does_not_mark_missing_bike_unavailable(
    tmp_path, monkeypatch, broad_config
):
    broad_config["llm"]["enabled"] = False
    broad_config["database"]["path"] = str(tmp_path / "listings.db")
    broad_config["search"]["sources"] = {
        "trademe": {
            "enabled": True,
            "allow_partial": True,
            "search_urls": ["https://www.trademe.co.nz/a/search"],
        }
    }
    with_store = Store(broad_config["database"]["path"])
    first = classify(machine(), broad_config)
    with_store.ingest([first], broad_config, "trademe", False)
    with_store.close()
    monkeypatch.setattr("motorcycle_monitor.service.collect", lambda *args: [])
    scan(broad_config, fetcher=SimpleNamespace(requests=0))
    scan(broad_config, fetcher=SimpleNamespace(requests=0))
    store = Store(broad_config["database"]["path"])
    try:
        assert store.all_listings()[0]["listing_status"] == "ACTIVE"
        row = store.db.execute(
            "SELECT details FROM collection_runs WHERE adapter='trademe' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert json.loads(row[0])["partial"] is True
    finally:
        store.close()


def test_acquisition_filters_follow_changed_policy(broad_config):
    broad_config["search"].update(
        max_price_nzd=14000, min_year=2019, max_odometer_km=20000
    )
    url = collectors.criteria_search_url(
        "https://www.trademe.co.nz/a/search?price_max=12500&year_min=2017&search_string=motorcycle",
        broad_config["search"],
    )
    values = parse_qs(urlsplit(url).query)
    assert values["price_max"] == ["14000"]
    assert values["year_min"] == ["2019"]
    assert values["odometer_max"] == ["20000"]
    assert values["search_string"] == ["motorcycle"]
