import json

from motorcycle_monitor.notifications import drain
from motorcycle_monitor.storage import Store


def events(store):
    return [
        r[0]
        for r in store.db.execute("SELECT event_type FROM notifications ORDER BY rowid")
    ]


def test_alerts_and_anchor(store, bike, config):
    store.ingest([bike()], config, "trademe", True)
    store.ingest([bike()], config, "trademe")
    assert events(store) == ["NEW_LISTING"]
    store.ingest([bike(asking_price_nzd=11700)], config, "trademe")
    assert events(store) == ["NEW_LISTING"]
    store.ingest([bike(asking_price_nzd=11499)], config, "trademe")
    assert events(store) == ["NEW_LISTING", "PRICE_DROP"]
    store.ingest([bike(asking_price_nzd=11499)], config, "trademe")
    assert events(store) == ["NEW_LISTING", "PRICE_DROP"]
    assert len(store.history("123")) == 5


def test_percent_smaller_than_absolute(store, bike, config):
    store.ingest([bike(asking_price_nzd=8000)], config, "trademe", True)
    store.ingest([bike(asking_price_nzd=7600)], config, "trademe")
    assert events(store) == ["NEW_LISTING", "PRICE_DROP"]


def test_baseline(store, bike, config):
    store.ingest([bike(listing_id=str(i)) for i in range(20)], config, "trademe")
    assert events(store) == ["BASELINE_SUMMARY"]
    store.ingest([bike(listing_id="new")], config, "trademe")
    assert events(store) == ["BASELINE_SUMMARY", "NEW_LISTING"]


def test_review_promotion(store, bike, config):
    store.ingest([bike(description="Unknown")], config, "trademe", True)
    store.ingest([bike(description="Unknown")], config, "trademe")
    store.ingest([bike()], config, "trademe")
    assert events(store) == ["REVIEW_REQUIRED", "NEW_LISTING"]


def test_auction_bid_no_price_drop(store, bike, config):
    store.ingest([bike()], config, "trademe", True)
    store.ingest(
        [bike(price_type="CURRENT_BID", asking_price_nzd=100)], config, "trademe"
    )
    assert "PRICE_DROP" not in events(store)


def test_relisting_is_suggested(store, bike, config):
    store.ingest([bike()], config, "trademe", True)
    store.ingest([bike(listing_id="456")], config, "trademe")
    assert len(store.all_listings()) == 2
    assert len(store.status()["possible_duplicates"]) == 1


def test_cross_source_duplicate(store, bike, config):
    store.ingest([bike(verified_identity="owner:stock-42")], config, "trademe", True)
    other = bike(
        source="dealer_tss",
        listing_id="dealer42",
        canonical_url="https://tssmotorcycles.co.nz/motorcycles/42",
        source_urls=["https://tssmotorcycles.co.nz/motorcycles/42"],
        verified_identity="owner:stock-42",
    )
    store.ingest([other], config, "dealer_tss", True)
    assert events(store) == ["NEW_LISTING"]
    assert len(store.all_listings()) == 1
    assert len(store.all_listings()[0]["source_urls"]) == 2
    assert len(store.history("123")) == 2


def test_transient_failure_does_not_end(store, bike, config):
    store.ingest([bike()], config, "trademe", True)
    store.record_run("trademe", "2026-10-12T00:00:00Z", "ERROR", {"error": "timeout"})
    assert store.all_listings()[0]["listing_status"] == "ACTIVE"
    assert events(store) == ["NEW_LISTING"]


def test_error_episode_deduplicated(store, config):
    for _ in range(5):
        store.record_run(
            "trademe",
            "2026-10-12T00:00:00Z",
            "ERROR",
            {"error": "HTTP 403; use native saved searches"},
        )
    assert events(store) == ["SYSTEM_ERROR"]
    store.record_run("trademe", "2026-10-12T00:00:00Z", "SUCCESS", {"parsed": 0})
    for _ in range(2):
        store.record_run(
            "trademe", "2026-10-12T00:00:00Z", "ERROR", {"error": "HTTP 429"}
        )
    assert events(store) == ["SYSTEM_ERROR", "SYSTEM_ERROR"]


def test_outbox_stable_retry(store, bike, config):
    config["mqtt"]["enabled"] = True
    store.ingest([bike()], config, "trademe", True)
    event_id = store.db.execute("SELECT event_id FROM notifications").fetchone()[0]

    def fail(topic, payload):
        raise ConnectionError("broker down")

    assert drain(store, config, fail)["failed"] == 1
    row = store.db.execute("SELECT * FROM notifications").fetchone()
    assert row["delivery_state"] == "PENDING" and row["attempts"] == 1
    sent = []
    assert (
        drain(store, config, lambda topic, payload: sent.append(json.loads(payload)))[
            "delivered"
        ]
        == 1
    )
    assert sent[0]["event_id"] == event_id
    assert drain(store, config, lambda *_: None)["delivered"] == 0


def test_history_survives_restart(tmp_path, bike, config):
    path = str(tmp_path / "persist.db")
    s = Store(path)
    s.ingest([bike()], config, "trademe")
    s.close()
    s = Store(path)
    assert len(s.history("123")) == 1
    assert s.db.execute("PRAGMA user_version").fetchone()[0] == 2
    s.close()


def test_reactivation(store, bike, config):
    store.ingest([bike()], config, "trademe", True)
    store.ingest([bike(listing_status="ENDED")], config, "trademe")
    store.ingest([bike()], config, "trademe")
    assert events(store) == ["NEW_LISTING", "LISTING_REACTIVATED"]


def test_baseline_one_summary_across_sources(store, bike, config):
    store.ingest([bike()], config, "trademe", baseline_event_id="scan-baseline")
    store.ingest(
        [bike(source="dealer_tss", listing_id="tss1")],
        config,
        "dealer_tss",
        baseline_event_id="scan-baseline",
    )
    assert events(store) == ["BASELINE_SUMMARY"]
    payload = json.loads(
        store.db.execute("SELECT payload FROM notifications").fetchone()[0]
    )
    assert len(payload["sources"]) == 2
    assert len(payload["listings"]) == 2


def test_alert_with_explicit_valuation(store, bike, config):
    config["changeover"] = {
        "scenarios": {
            "dealer:TSS Motorcycles": {
                "kind": "trade_in",
                "valuation_id": 1,
                "expenses_nzd": 200,
            }
        }
    }
    quote = {
        "kind": "trade_in",
        "seller": "TSS Motorcycles",
        "basis": "ACTUAL_QUOTE",
        "value_nzd": 4000,
        "provenance": "written quote",
    }
    with store.db:
        store.db.execute(
            "INSERT INTO trade_in_quotes(data) VALUES (?)", (json.dumps(quote),)
        )
    store.ingest(
        [
            bike(
                seller_type="DEALER",
                dealer_name="TSS Motorcycles",
                trade_in_available="YES",
                orc_nzd=300,
            )
        ],
        config,
        "trademe",
        True,
    )
    payload = json.loads(
        store.db.execute("SELECT payload FROM notifications").fetchone()[0]
    )
    assert payload["changeover"]["changeover_nzd"] == 8500


def test_exact_cross_source_url_reference(store, bike, config):
    store.ingest([bike()], config, "trademe", True)
    store.ingest(
        [
            bike(
                source="dealer_tss",
                listing_id="tss42",
                canonical_url="https://tssmotorcycles.co.nz/motorcycles/42",
                source_urls=[
                    "https://tssmotorcycles.co.nz/motorcycles/42",
                    "https://www.trademe.co.nz/listing/123?tracking=other",
                ],
            )
        ],
        config,
        "dealer_tss",
        True,
    )
    assert len(store.all_listings()) == 1
    assert events(store) == ["NEW_LISTING"]
    payload = json.loads(
        store.db.execute("SELECT payload FROM notifications").fetchone()[0]
    )
    assert len(payload["listing"]["source_urls"]) == 3


def test_tracking_query_does_not_count_as_changed(store, bike, config):
    store.ingest(
        [bike(canonical_url="https://www.trademe.co.nz/listing/123?rsqid=first")],
        config,
        "trademe",
        True,
    )
    before = store.all_listings()[0]["last_changed_utc"]
    store.ingest(
        [bike(canonical_url="https://www.trademe.co.nz/listing/123?rsqid=second")],
        config,
        "trademe",
    )
    assert store.all_listings()[0]["last_changed_utc"] == before
    assert events(store) == ["NEW_LISTING"]


def test_missing_complete_scans_mark_unavailable_and_return_reactivates(
    store, bike, config, monkeypatch
):
    import motorcycle_monitor.storage as storage

    stamp = "2026-10-13T00:00:00+00:00"
    monkeypatch.setattr(storage, "utc_now", lambda: stamp)
    store.ingest([bike()], config, "trademe", True)
    stamp = "2026-10-14T00:00:00+00:00"
    store.ingest([], config, "trademe")
    assert store.all_listings()[0]["listing_status"] == "ACTIVE"
    # Repeating a manual scan within twelve hours is not additional evidence.
    store.ingest([], config, "trademe")
    assert store.all_listings()[0]["listing_status"] == "ACTIVE"
    stamp = "2026-10-15T00:00:00+00:00"
    store.ingest([], config, "trademe")
    data = store.all_listings()[0]
    assert data["listing_status"] == "UNKNOWN"
    assert data["evidence"]["availability"]["status"] == "NOT_SEEN"
    assert events(store) == ["NEW_LISTING", "LISTING_UNAVAILABLE"]
    stamp = "2026-10-16T00:00:00+00:00"
    store.ingest([bike()], config, "trademe")
    assert store.all_listings()[0]["listing_status"] == "ACTIVE"
    assert events(store)[-1] == "LISTING_REACTIVATED"


def test_failed_scan_resets_absence_streak(store, bike, config, monkeypatch):
    import motorcycle_monitor.storage as storage

    stamp = "2026-10-13T00:00:00+00:00"
    monkeypatch.setattr(storage, "utc_now", lambda: stamp)
    store.ingest([bike()], config, "trademe", True)
    stamp = "2026-10-14T00:00:00+00:00"
    store.ingest([], config, "trademe")
    store.record_run("trademe", stamp, "ERROR", {"error": "HTTP 403"})
    stamp = "2026-10-15T00:00:00+00:00"
    store.ingest([], config, "trademe")
    assert store.all_listings()[0]["listing_status"] == "ACTIVE"


def test_other_active_source_prevents_unavailable(store, bike, config, monkeypatch):
    import motorcycle_monitor.storage as storage

    stamp = "2026-10-13T00:00:00+00:00"
    monkeypatch.setattr(storage, "utc_now", lambda: stamp)
    store.ingest([bike(verified_identity="same")], config, "trademe", True)
    store.ingest(
        [bike(source="dealer_tss", listing_id="other", verified_identity="same")],
        config,
        "dealer_tss",
        True,
    )
    for stamp in ["2026-10-14T00:00:00+00:00", "2026-10-15T00:00:00+00:00"]:
        store.ingest([], config, "trademe")
    assert store.all_listings()[0]["listing_status"] == "ACTIVE"
    assert "LISTING_UNAVAILABLE" not in events(store)


def test_import_does_not_mark_other_bikes_missing(store, bike, config):
    store.ingest([bike()], config, "trademe", True)
    store.ingest([], config, "trademe", track_availability=False)
    assert (
        store.db.execute("SELECT missed_scans FROM source_availability").fetchone()[0]
        == 0
    )


def test_scope_change_resets_missing_evidence(store, bike, config, monkeypatch):
    import motorcycle_monitor.storage as storage

    stamp = "2026-10-13T00:00:00+00:00"
    monkeypatch.setattr(storage, "utc_now", lambda: stamp)
    store.ingest([bike()], config, "trademe", True)
    stamp = "2026-10-14T00:00:00+00:00"
    store.ingest([], config, "trademe")
    config["search"]["sources"]["trademe"]["search_urls"] = [
        "https://www.trademe.co.nz/different-search"
    ]
    stamp = "2026-10-15T00:00:00+00:00"
    store.ingest([], config, "trademe")
    assert store.all_listings()[0]["listing_status"] == "ACTIVE"
    assert (
        store.db.execute("SELECT missed_scans FROM source_availability").fetchone()[0]
        == 0
    )


def test_version_one_database_migrates(tmp_path, bike, config):
    import sqlite3

    from motorcycle_monitor.storage import MIGRATIONS

    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.executescript(MIGRATIONS[0] + "\nPRAGMA user_version=1;")
    db.close()
    upgraded = Store(path)
    assert upgraded.db.execute("PRAGMA user_version").fetchone()[0] == 2
    upgraded.ingest([bike()], config, "trademe")
    assert upgraded.all_listings()[0]["listing_status"] == "ACTIVE"
    upgraded.close()


def test_return_on_new_exact_source_reactivates(store, bike, config, monkeypatch):
    import motorcycle_monitor.storage as storage

    stamp = "2026-10-13T00:00:00+00:00"
    monkeypatch.setattr(storage, "utc_now", lambda: stamp)
    store.ingest([bike(verified_identity="same-bike")], config, "trademe", True)
    for stamp in ["2026-10-14T00:00:00+00:00", "2026-10-15T00:00:00+00:00"]:
        store.ingest([], config, "trademe")
    stamp = "2026-10-16T00:00:00+00:00"
    store.ingest(
        [
            bike(
                source="dealer_tss",
                listing_id="returned",
                verified_identity="same-bike",
            )
        ],
        config,
        "dealer_tss",
        True,
    )
    listing = store.all_listings()[0]
    assert listing["listing_status"] == "ACTIVE"
    assert listing["last_seen_utc"] == stamp
    assert listing["last_changed_utc"] == stamp
    assert events(store)[-1] == "LISTING_REACTIVATED"


def test_rejected_disappearance_does_not_notify(store, bike, config, monkeypatch):
    import motorcycle_monitor.storage as storage

    stamp = "2026-10-13T00:00:00+00:00"
    monkeypatch.setattr(storage, "utc_now", lambda: stamp)
    store.ingest([bike(asking_price_nzd=15000)], config, "trademe", True)
    for stamp in ["2026-10-14T00:00:00+00:00", "2026-10-15T00:00:00+00:00"]:
        store.ingest([], config, "trademe")
    assert store.all_listings()[0]["listing_status"] == "UNKNOWN"
    assert events(store) == []


def test_health_retains_latest_result_for_every_source(store):
    for number in range(12):
        store.record_run(f"source-{number}", "2026-10-16T00:00:00+00:00", "SUCCESS", {})
    store.record_run(
        "source-0", "2026-10-16T01:00:00+00:00", "ERROR", {"error": "blocked"}
    )
    runs = store.status()["runs"]
    assert len(runs) == 12
    assert {row["adapter"] for row in runs} == {
        f"source-{number}" for number in range(12)
    }
    assert (
        next(row for row in runs if row["adapter"] == "source-0")["outcome"] == "ERROR"
    )
