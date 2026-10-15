import json
from io import BytesIO
from pathlib import Path

from motorcycle_monitor.scheduler import scan_lock
from motorcycle_monitor.storage import Store
from motorcycle_monitor.web import Dashboard, snapshot


def call(config, path="/", query="", method="GET"):
    captured = []
    body = b"".join(
        Dashboard(config)(
            {
                "PATH_INFO": path,
                "QUERY_STRING": query,
                "REQUEST_METHOD": method,
                "wsgi.input": BytesIO(),
            },
            lambda status, headers: captured.append((status, dict(headers))),
        )
    )
    return *captured[0], body


def test_dashboard_serves_packaged_assets(config):
    status, headers, body = call(config)
    assert status == "200 OK"
    assert b"Motorcycle Monitor" in body
    assert b"/dashboard.js" in body
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert "nosniff" == headers["X-Content-Type-Options"]
    for path, kind in [
        ("/dashboard.js", "text/javascript"),
        ("/dashboard.css", "text/css"),
    ]:
        status, headers, body = call(config, path)
        assert status == "200 OK" and kind in headers["Content-Type"] and body


def test_uninitialized_dashboard_does_not_create_database(config):
    status, _, body = call(config, "/api/results")
    assert status == "200 OK"
    assert json.loads(body)["initialized"] is False
    assert not Path(config["database"]["path"]).exists()


def test_snapshot_during_scan_is_readonly(config, bike):
    store = Store(config["database"]["path"])
    store.ingest([bike()], config, "trademe")
    with scan_lock(config["database"]["path"] + ".lock"):
        store.db.execute("BEGIN IMMEDIATE")
        result = snapshot(config)
        assert result["initialized"]
        assert result["listings"][0]["title"] == "2021 Kawasaki Ninja 650"
        assert result["listings"][0]["changeover"]["changeover_nzd"] is None
        store.db.rollback()
    assert store.db.execute("SELECT count(*) FROM observations").fetchone()[0] == 1
    store.close()


def test_dashboard_history_and_no_mutations(config, bike):
    store = Store(config["database"]["path"])
    store.ingest([bike()], config, "trademe")
    store.close()
    status, _, body = call(config, "/api/history", "id=trademe%3A123")
    assert status == "200 OK" and len(json.loads(body)["observations"]) == 1
    assert call(config, "/api/history")[0] == "400 Bad Request"
    assert call(config, "/api/results", method="POST")[0] == "405 Method Not Allowed"
    assert call(config, "/../../config.yaml")[0] == "404 Not Found"
    assert call(config, method="HEAD")[2] == b""


def test_dashboard_filters_unsafe_links(config, bike):
    store = Store(config["database"]["path"])
    store.ingest(
        [
            bike(
                title="<script>alert(1)</script> Ninja 650",
                source_urls=[
                    "javascript:alert(1)",
                    "https://evil.invalid/",
                    "https://www.trademe.co.nz/listing/123",
                ],
            )
        ],
        config,
        "trademe",
    )
    store.close()
    result = snapshot(config)
    assert result["listings"][0]["source_urls"] == [
        "https://www.trademe.co.nz/listing/123"
    ]
    # Advert text is sent as JSON, then rendered using textContent by the frontend.
    assert "<script>" in result["listings"][0]["title"]


def test_dashboard_database_failure_is_visible(config):
    Path(config["database"]["path"]).write_text("not SQLite")
    status, _, body = call(config, "/api/results")
    assert status == "503 Service Unavailable"
    assert "could not be read" in json.loads(body)["error"]
