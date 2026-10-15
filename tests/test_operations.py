import httpx
import pytest

from motorcycle_monitor.cli import main
from motorcycle_monitor.collectors import CollectionError, Fetcher
from motorcycle_monitor.config import load_config, validate
from motorcycle_monitor.normalization import date_utc, mileage, money, safe_url
from motorcycle_monitor.scheduler import scan_lock
from motorcycle_monitor.service import scan
from motorcycle_monitor.trade_in import changeover


@pytest.mark.parametrize("status", [403, 429])
def test_blocked_no_retries(config, status):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(status))
    )
    f = Fetcher(config["collector"], client=client)
    with pytest.raises(CollectionError, match=f"HTTP {status}"):
        f.get("https://www.trademe.co.nz/search", ["www.trademe.co.nz"])
    assert f.requests == 1
    f.close()


def test_request_cache(config):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, text="<html>test</html>", headers={"content-type": "text/html"}
            )
        )
    )
    f = Fetcher(config["collector"], client=client)
    f.get("https://www.trademe.co.nz/search", ["www.trademe.co.nz"])
    f.get("https://www.trademe.co.nz/search", ["www.trademe.co.nz"])
    assert f.requests == 1
    f.close()


def test_redirect_outside_hosts(config):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "http://evil.invalid/"})
        )
    )
    f = Fetcher(config["collector"], client=client)
    with pytest.raises(ValueError):
        f.get("https://www.trademe.co.nz/search", ["www.trademe.co.nz"])
    assert f.requests == 1
    f.close()


def test_normalization():
    assert money("NZ$12,500") == 12500
    assert money("NZD 12,500.00") == 12500
    assert money("POA") is None
    assert money("USD 500") is None
    assert mileage("10,000 km") == 10000
    assert mileage("100 miles") == 161
    assert mileage(None) is None
    assert date_utc("2026-10-13T08:00:00+13:00") == "2026-10-12T19:00:00+00:00"
    with pytest.raises(ValueError):
        date_utc("2026-10-13T08:00:00")


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://www.trademe.co.nz.evil.invalid/",
        "https://user:secret@www.trademe.co.nz/",
        "http://127.0.0.1/",
        "https://www.trademe.co.nz:444/",
    ],
)
def test_unsafe_links(url):
    with pytest.raises(ValueError):
        safe_url(url, ["www.trademe.co.nz"])


def test_lock(tmp_path):
    with scan_lock(str(tmp_path / "test.lock")):
        with pytest.raises(RuntimeError, match="Another scan"):
            with scan_lock(str(tmp_path / "test.lock")):
                pass
    with scan_lock(str(tmp_path / "test.lock")):
        pass


def test_dry_run_no_files(config, tmp_path):
    before = set(tmp_path.rglob("*"))
    result = scan(config, dry_run=True, import_file="tests/fixtures/manual.json")
    assert not result["errors"]
    assert result["sources"]["trademe"]["accepted"] == 1
    assert set(tmp_path.rglob("*")) == before


def test_dry_run_does_not_touch_existing_database(config, tmp_path):
    scan(config, import_file="tests/fixtures/manual.json")
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    scan(config, dry_run=True, import_file="tests/fixtures/manual.json")
    assert {
        str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    } == before


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("collector", "max_concurrency", 2),
        ("collector", "request_interval_seconds", 0),
        ("mqtt", "qos", 0),
        ("alerts", "price_drop_percent", -1),
        ("mqtt", "enabled", "false"),
    ],
)
def test_bad_config(config, section, key, value):
    config[section][key] = value
    with pytest.raises(ValueError):
        validate(config)


def test_changeover(bike):
    listing = bike(
        orc_nzd=300,
        seller_type="DEALER",
        dealer_name="TSS Motorcycles",
        trade_in_available="YES",
    ).to_dict()
    quote = {
        "kind": "trade_in",
        "seller": "TSS Motorcycles",
        "value_nzd": 4000,
        "basis": "ACTUAL_QUOTE",
        "quote_date": "2026-10-13",
        "provenance": "written offer",
    }
    result = changeover(listing, quote, 200)
    assert result["changeover_nzd"] == 8500
    assert result["valuation"]["basis"] == "ACTUAL_QUOTE"
    listing["seller_type"] = "PRIVATE"
    quote = {
        "kind": "private_sale",
        "value_nzd": 4500,
        "basis": "ESTIMATE",
        "provenance": "owner estimate",
    }
    assert changeover(listing, quote, 200)["changeover_nzd"] == 8000
    assert changeover(listing, quote)["changeover_nzd"] is None


def test_cli_validate_and_import(tmp_path, capsys):
    import yaml

    config = load_config("config.example.yaml")
    config["database"]["path"] = str(tmp_path / "cli.db")
    config["logging"]["path"] = None
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    assert main(["--config", str(path), "validate-config"]) == 0
    assert (
        main(
            [
                "--config",
                str(path),
                "scan",
                "--import-file",
                "tests/fixtures/manual.json",
            ]
        )
        == 0
    )
    assert main(["--config", str(path), "listings"]) == 0
    assert main(["--config", str(path), "history", "demo-650"]) == 0
    assert main(["--config", str(path), "status"]) == 0


def test_conservative_unit_normalization():
    assert mileage("10000.1 km") == 10001
    assert money("NZ$12,50") is None


def test_readable_listings_and_json_option(tmp_path, config, bike, capsys):
    import json

    import yaml

    from motorcycle_monitor.storage import Store

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    store = Store(config["database"]["path"])
    store.ingest([bike()], config, "trademe")
    store.close()
    assert main(["--config", str(path), "listings"]) == 0
    text = capsys.readouterr().out
    assert "[AVAILABLE] [ACCEPTED]" in text
    assert "NZ$12,000" in text
    assert "https://www.trademe.co.nz/listing/123" in text
    assert main(["--config", str(path), "listings", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["listing_id"] == "123"


def test_read_commands_work_during_scan(config, bike, tmp_path, capsys):
    import yaml

    from motorcycle_monitor.storage import Store

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    store = Store(config["database"]["path"])
    store.ingest([bike()], config, "trademe")
    with scan_lock(config["database"]["path"] + ".lock"):
        # Read the last committed results even while a write transaction is open.
        store.db.execute("BEGIN IMMEDIATE")
        for args in [["listings"], ["status"], ["history", "123"]]:
            assert main(["--config", str(path), *args]) == 0
        assert main(["--config", str(path), "publish-pending"]) == 1
        store.db.rollback()
    store.close()


def test_fresh_scan_bypasses_http_cache(config, tmp_path):
    config["collector"]["cache_seconds"] = 3600
    old = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, text="<html>old</html>", headers={"content-type": "text/html"}
            )
        )
    )
    fetcher = Fetcher(config["collector"], cache_dir=tmp_path / "cache", client=old)
    assert (
        fetcher.get("https://www.trademe.co.nz/search", ["www.trademe.co.nz"])
        == "<html>old</html>"
    )
    fetcher.close()
    config["collector"]["cache_seconds"] = 0
    new = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, text="<html>new</html>", headers={"content-type": "text/html"}
            )
        )
    )
    fetcher = Fetcher(config["collector"], cache_dir=tmp_path / "cache", client=new)
    assert (
        fetcher.get("https://www.trademe.co.nz/search", ["www.trademe.co.nz"])
        == "<html>new</html>"
    )
    assert fetcher.requests == 1
    fetcher.close()
