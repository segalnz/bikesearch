"""Read-only LAN dashboard over the existing SQLite database."""

import json
import logging
import sqlite3
from importlib.resources import files
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from .filtering import current_criteria, priority
from .normalization import safe_url, utc_now
from .storage import Store
from .suitability import describe_search

log = logging.getLogger(__name__)


def dashboard_metadata(config: dict) -> dict:
    """Expose only presentation-safe settings; never return the full configuration."""
    return {
        "criteria_summary": describe_search(config["search"]),
        "operational_plan": config["search"].get("_operational_plan"),
        "generated_at": utc_now(),
        "refresh_seconds": config.get("web", {}).get("refresh_seconds", 60),
        "mqtt_enabled": config["mqtt"]["enabled"],
        "deployment_id": config.get("web", {}).get("deployment_id", "development"),
        "area": config["search"].get("area_label", "Nationwide"),
        "demo": config.get("web", {}).get("demo", False),
        "search_mode": config["search"].get("mode", "models"),
        "requirements": config["search"].get("requirements"),
        "preferences": config["search"].get("preferences"),
        "min_year": config["search"].get("min_year"),
        "criteria": {
            key: config["search"][key]
            for key in ("models", "max_price_nzd", "max_odometer_km")
        },
        "source_labels": {
            name: source.get("dealer_name", name)
            for name, source in config["search"]["sources"].items()
        },
        "indexed_search_enabled": any(
            source.get("enabled") and source.get("parser") == "indexed_search"
            for source in config["search"]["sources"].values()
        ),
    }


def snapshot(config: dict) -> dict:
    from .search_plan import read_plan

    plan = read_plan(config)
    config["search"]["_operational_plan"] = plan or {}
    path = config["database"]["path"]
    if not Path(path).exists():
        return {
            "initialized": False,
            "listings": [],
            "runs": [],
            "pending_events": 0,
            "possible_duplicates": [],
            **dashboard_metadata(config),
        }
    store = Store(path, readonly=True)
    try:
        store.db.execute("BEGIN")
        listings = [current_criteria(item, config) for item in store.all_listings()]
        hosts = [
            host
            for source in config["search"]["sources"].values()
            for host in source.get("allowed_hosts", [])
        ]
        for listing in listings:
            link_hosts = hosts
            source_config = config["search"]["sources"].get(listing["source"], {})
            if source_config.get("parser") == "indexed_search":
                link_hosts = [*hosts, urlsplit(listing["canonical_url"]).hostname]
            urls = []
            for url in listing.get("source_urls", []) or [listing["canonical_url"]]:
                try:
                    urls.append(safe_url(url, link_hosts))
                except (ValueError, TypeError):
                    pass
            listing["source_urls"] = urls
            listing["changeover"] = store.alert_payload(listing, "COMPARISON", config)[
                "changeover"
            ]
            support = store.db.execute(
                "SELECT data FROM model_support WHERE model=?", (listing.get("model"),)
            ).fetchone()
            listing["model_support"] = json.loads(support[0]) if support else None
        complete_groups = {
            state: all(
                item["changeover"]["changeover_nzd"] is not None
                for item in listings
                if item["classification"] == state
            )
            for state in {item["classification"] for item in listings}
        }
        for listing in listings:
            listing["ranking_basis"] = (
                "changeover"
                if complete_groups[listing["classification"]]
                else "asking_price"
            )
        listings.sort(
            key=lambda item: priority(
                item
                if item["ranking_basis"] == "changeover"
                else {**item, "changeover": {}},
                config,
            )
        )
        status = store.status()
        return {
            **status,
            "initialized": True,
            "listings": listings,
            **dashboard_metadata(config),
        }
    finally:
        store.close()


class Dashboard:
    def __init__(self, config: dict):
        self.config = config

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")
        method = environ.get("REQUEST_METHOD", "GET")
        headers = [
            ("X-Content-Type-Options", "nosniff"),
            ("Cache-Control", "no-store"),
            (
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            ),
            ("Referrer-Policy", "no-referrer"),
        ]
        status = "200 OK"
        content_type = "application/json; charset=utf-8"
        try:
            if method not in {"GET", "HEAD"}:
                status, data = (
                    "405 Method Not Allowed",
                    {"error": "Dashboard is read-only"},
                )
                headers.append(("Allow", "GET, HEAD"))
            elif path in {"/", "/dashboard.css", "/dashboard.js"}:
                name = {
                    "/": "index.html",
                    "/dashboard.css": "dashboard.css",
                    "/dashboard.js": "dashboard.js",
                }[path]
                content_type = {
                    "/": "text/html; charset=utf-8",
                    "/dashboard.css": "text/css; charset=utf-8",
                    "/dashboard.js": "text/javascript; charset=utf-8",
                }[path]
                data = (
                    files("motorcycle_monitor")
                    .joinpath("web_assets", name)
                    .read_bytes()
                )
            elif path == "/api/results":
                data = snapshot(self.config)
            elif path == "/api/history":
                identity = parse_qs(environ.get("QUERY_STRING", "")).get("id", [""])[0]
                if not identity or len(identity) > 300:
                    status, data = (
                        "400 Bad Request",
                        {"error": "A listing history ID is required"},
                    )
                elif not Path(self.config["database"]["path"]).exists():
                    data = {"observations": []}
                else:
                    store = Store(self.config["database"]["path"], readonly=True)
                    try:
                        data = {"observations": store.history(identity)}
                    finally:
                        store.close()
            else:
                status, data = "404 Not Found", {"error": "Page not found"}
        except (sqlite3.Error, OSError, ValueError, KeyError) as error:
            log.error("Dashboard read failed: %s", error)
            status, data = (
                "503 Service Unavailable",
                {
                    "error": "Saved results could not be read. Check the dashboard service log."
                },
            )
        body = (
            data
            if isinstance(data, bytes)
            else json.dumps(data, ensure_ascii=False).encode()
        )
        headers.extend(
            [("Content-Type", content_type), ("Content-Length", str(len(body)))]
        )
        start_response(status, headers)
        return [body] if method != "HEAD" else []


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class RequestLogger(WSGIRequestHandler):
    def log_message(self, format, *args):
        log.info(format, *args)


def serve(config: dict, host: str | None = None, port: int | None = None) -> None:
    host = host if host is not None else config.get("web", {}).get("host", "0.0.0.0")
    port = port if port is not None else config.get("web", {}).get("port", 8765)
    if not 1 <= port <= 65535:
        raise ValueError("Dashboard port must be between 1 and 65535")
    with make_server(
        host,
        port,
        Dashboard(config),
        server_class=ThreadedServer,
        handler_class=RequestLogger,
    ) as server:
        log.info("Dashboard listening on http://%s:%s", host, port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
