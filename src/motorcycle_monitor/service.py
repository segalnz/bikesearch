"""Collection orchestration; dry-run uses no database, lock or disk cache."""

import json
import logging
import uuid
from pathlib import Path

from .collectors import Fetcher, collect
from .filtering import classify
from .normalization import safe_url, utc_now
from .notifications import drain
from .ports import CandidateReviewer, PageFetcher
from .scheduler import scan_lock
from .schema import Listing
from .storage import Store

log = logging.getLogger(__name__)


def import_listings(path: str, config: dict) -> list[Listing]:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError("Import must be a JSON array of normalized listings")
    result = []
    for item in data:
        listing = Listing.from_dict(item)
        options = config["search"]["sources"].get(listing.source)
        if options is None:
            raise ValueError(f"Import source {listing.source!r} is not configured")
        for url in [listing.canonical_url, *listing.source_urls]:
            safe_url(url, options.get("allowed_hosts", []))
        listing.source_urls = list(
            dict.fromkeys([listing.canonical_url, *listing.source_urls])
        )
        listing.evidence["fetch"] = {
            "kind": "manual_import",
            "file": str(Path(path).resolve()),
            "observed_at": utc_now(),
        }
        result.append(classify(listing, config))
    return result


def scan(
    config: dict,
    dry_run: bool = False,
    notify_initial: bool = False,
    import_file: str | None = None,
    fetcher: PageFetcher | None = None,
    reviewer: CandidateReviewer | None = None,
) -> dict:
    database_path = config["database"]["path"]
    if dry_run:
        return _scan(
            config,
            None,
            notify_initial,
            import_file,
            fetcher,
            dry_run=True,
            reviewer=reviewer,
        )
    with scan_lock(database_path + ".lock"):
        store = Store(database_path)
        try:
            return _scan(
                config, store, notify_initial, import_file, fetcher, reviewer=reviewer
            )
        finally:
            store.close()


def _scan(
    config: dict,
    store: Store | None,
    notify_initial: bool,
    import_file: str | None,
    fetcher: PageFetcher | None,
    dry_run: bool = False,
    reviewer: CandidateReviewer | None = None,
) -> dict:
    owned_fetcher = fetcher is None
    fetcher = fetcher or Fetcher(
        config["collector"],
        None if dry_run else Path(config["database"]["path"]).parent / "http-cache",
    )
    baseline_event_id = str(uuid.uuid4())
    results = {"dry_run": dry_run, "sources": {}, "errors": []}
    owned_reviewer = reviewer is None
    if reviewer is None and config["llm"]["enabled"]:
        from .reviewer import Reviewer

        reviewer = Reviewer(
            config["llm"],
            None if dry_run else Path(config["database"]["path"]).parent / "ai-cache",
        )
    researcher = None
    research_fetcher = None
    if (
        config["search"].get("mode") == "all_models"
        and config["llm"].get("enabled")
        and config["llm"].get("research_enabled")
    ):
        from .research import ModelResearcher

        research_fetcher = Fetcher(
            {
                **config["collector"],
                "max_requests": 60,
                "max_retries": 0,
                "request_interval_seconds": 2,
                "request_timeout_seconds": 15,
                "allow_research_rss": True,
                "allow_research_pdf": True,
            },
            None
            if dry_run
            else Path(config["database"]["path"]).parent / "research-http-cache",
        )
        researcher = ModelResearcher(
            config["llm"],
            research_fetcher,
            None
            if dry_run
            else Path(config["database"]["path"]).parent / "model-cache",
        )
    try:
        imported = import_listings(import_file, config) if import_file else None
        if imported is not None:
            sources = {
                listing.source: config["search"]["sources"][listing.source]
                for listing in imported
            }
            if not sources:
                raise ValueError("Empty import is not a completed source baseline")
        else:
            sources = {
                name: options
                for name, options in config["search"]["sources"].items()
                if options.get("enabled", False)
            }
        if not sources:
            results["errors"].append(
                "No enabled sources; configure search URLs or use --import-file"
            )
        for name, options in sources.items():
            started = utc_now()
            requests_before = fetcher.requests
            try:
                listings = (
                    [x for x in imported if x.source == name]
                    if imported is not None
                    else collect(name, options, fetcher, config)
                )
                listings = [classify(x, config) for x in listings]
                if researcher:
                    from .research_sources import document_urls

                    researcher.source_attempts = 0
                    for listing in sorted(
                        listings,
                        key=lambda x: (
                            not bool(document_urls(x)),
                            x.power_status != "UNRESTRICTED",
                            -x.evidence.get("suitability", {}).get(
                                "preference_matches", 0
                            ),
                        ),
                    ):
                        if listing.classification != "REJECTED":
                            researcher.research(listing)
                            classify(listing, config)
                if reviewer:
                    candidates = sorted(
                        listings,
                        key=lambda x: (
                            x.classification == "REJECTED",
                            x.power_status != "UNRESTRICTED",
                            -x.evidence.get("suitability", {}).get(
                                "preference_matches", 0
                            ),
                        ),
                    )
                    for listing in candidates:
                        if listing.classification != "REJECTED":
                            reviewer.review(listing, config["search"])
                partial = options.get("allow_partial", False)
                if store:
                    counts = store.ingest(
                        listings,
                        config,
                        name,
                        notify_initial,
                        baseline_event_id=baseline_event_id,
                        track_availability=imported is None and not partial,
                    )
                    store.record_run(
                        name,
                        started,
                        "SUCCESS",
                        {
                            **counts,
                            "urls_checked": options.get("search_urls", []),
                            "requests": fetcher.requests - requests_before,
                            "partial": partial,
                            "warning": "Bounded discovery; not a complete inventory. Missing bikes are not marked unavailable."
                            if partial
                            else None,
                        },
                    )
                else:
                    counts = {
                        "parsed": len(listings),
                        "accepted": sum(
                            x.classification == "ACCEPTED" for x in listings
                        ),
                        "review": sum(x.classification == "REVIEW" for x in listings),
                        "filtered": sum(
                            x.classification == "REJECTED" for x in listings
                        ),
                        "listings": [x.to_dict() for x in listings],
                    }
                results["sources"][name] = {"outcome": "SUCCESS", **counts}
                log.info(
                    "%s collection: %s",
                    name,
                    {k: v for k, v in counts.items() if k != "listings"},
                )
            except Exception as error:
                message = f"{name}: {error}"
                results["errors"].append(message)
                results["sources"][name] = {"outcome": "ERROR", "error": str(error)}
                log.error("%s", message)
                if store:
                    store.record_run(
                        name,
                        started,
                        "ERROR",
                        {
                            "error": str(error),
                            "urls_checked": options.get("search_urls", []),
                        },
                    )
        if store:
            with store.db:
                row = store.db.execute(
                    "SELECT payload FROM notifications WHERE event_id=?",
                    (baseline_event_id,),
                ).fetchone()
                if row:
                    payload = json.loads(row[0])
                    for listing in payload["listings"]:
                        current = store.db.execute(
                            "SELECT l.data FROM listings l JOIN listing_sources s ON s.listing_key=l.id WHERE s.source=? AND s.listing_id=?",
                            (listing["source"], listing["listing_id"]),
                        ).fetchone()
                        if current:
                            listing["source_urls"] = json.loads(current[0])[
                                "source_urls"
                            ]
                    store.db.execute(
                        "UPDATE notifications SET payload=? WHERE event_id=?",
                        (json.dumps(payload), baseline_event_id),
                    )
            published = drain(store, config)
            results["notifications"] = published
            store.record_run(
                "publisher",
                utc_now(),
                "ERROR" if published["failed"] else "SUCCESS",
                {
                    **published,
                    "error": "MQTT delivery failed; event retained for retry"
                    if published["failed"]
                    else None,
                },
            )
            if published["failed"]:
                results["errors"].append(
                    "MQTT delivery failed; event retained for retry"
                )
    finally:
        if researcher:
            researcher.close()
        if research_fetcher:
            research_fetcher.close()
        if owned_reviewer and reviewer:
            reviewer.close()
        if owned_fetcher:
            fetcher.close()
    return results
