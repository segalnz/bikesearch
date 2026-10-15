"""Versioned SQLite persistence and a transactional notification outbox."""

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from .model_support import SEEDS
from .normalization import canonical_url, utc_now
from .schema import Listing
from .trade_in import changeover

MIGRATIONS = [
    """
CREATE TABLE listings (
 id INTEGER PRIMARY KEY, source TEXT NOT NULL, listing_id TEXT NOT NULL,
 data TEXT NOT NULL, fingerprint TEXT NOT NULL, verified_identity TEXT,
 last_event_price INTEGER, first_seen_utc TEXT NOT NULL, last_seen_utc TEXT NOT NULL,
 last_changed_utc TEXT NOT NULL, UNIQUE(source, listing_id));
CREATE UNIQUE INDEX verified_identity_unique ON listings(verified_identity) WHERE verified_identity IS NOT NULL;
CREATE TABLE listing_sources (
 source TEXT NOT NULL, listing_id TEXT NOT NULL, listing_key INTEGER NOT NULL REFERENCES listings(id),
 url TEXT NOT NULL, UNIQUE(source, listing_id));
CREATE TABLE observations (
 id INTEGER PRIMARY KEY, listing_key INTEGER NOT NULL REFERENCES listings(id), observed_at TEXT NOT NULL,
 asking_price_nzd INTEGER, odometer_km INTEGER, listing_status TEXT NOT NULL,
 fingerprint TEXT NOT NULL, provenance TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE notifications (
 event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, listing_key INTEGER REFERENCES listings(id),
 payload TEXT NOT NULL, delivery_state TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
 last_error TEXT, created_at TEXT NOT NULL, delivered_at TEXT);
CREATE TABLE collection_runs (
 id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT NOT NULL, adapter TEXT NOT NULL,
 outcome TEXT NOT NULL, details TEXT NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE duplicate_candidates (
 id INTEGER PRIMARY KEY, listing_key INTEGER REFERENCES listings(id), other_key INTEGER REFERENCES listings(id),
 reason TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'REVIEW', UNIQUE(listing_key, other_key));
CREATE TABLE trade_in_quotes (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE private_sale_estimates (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE model_support (model TEXT PRIMARY KEY, data TEXT NOT NULL);
""",
    """
CREATE TABLE source_availability (
 source TEXT NOT NULL, listing_id TEXT NOT NULL, missed_scans INTEGER NOT NULL DEFAULT 0,
 last_missing_utc TEXT, status TEXT NOT NULL DEFAULT 'ACTIVE',
 PRIMARY KEY(source,listing_id),
 FOREIGN KEY(source,listing_id) REFERENCES listing_sources(source,listing_id));
INSERT INTO source_availability(source,listing_id) SELECT source,listing_id FROM listing_sources;
""",
]


def dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def fingerprint(data: dict) -> str:
    content = {
        k: v
        for k, v in data.items()
        if k
        not in {
            "first_seen_utc",
            "last_seen_utc",
            "last_changed_utc",
            "evidence",
            "source_urls",
        }
    }
    if content.get("canonical_url"):
        content["canonical_url"] = canonical_url(content["canonical_url"])
    return hashlib.sha256(dumps(content).encode()).hexdigest()


class Store:
    def __init__(self, path: str, readonly: bool = False):
        if readonly:
            self.db = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
        else:
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        if not readonly:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.migrate()

    def close(self) -> None:
        self.db.close()

    def migrate(self) -> None:
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise ValueError(
                "Database is newer than this monitor; upgrade the software"
            )
        for index in range(version, len(MIGRATIONS)):
            self.db.executescript(
                f"BEGIN IMMEDIATE;\n{MIGRATIONS[index]}\nPRAGMA user_version={index + 1};\nCOMMIT;"
            )
        with self.db:
            for model, data in SEEDS.items():
                self.db.execute(
                    "INSERT OR IGNORE INTO model_support VALUES (?,?)",
                    (model, dumps(data)),
                )

    def enqueue(self, event_type: str, listing_key: int | None, payload: dict) -> str:
        event_id = str(uuid.uuid4())
        payload = {
            "schema_version": 1,
            "event_id": event_id,
            "event_type": event_type,
            "listing_key": listing_key,
            "observed_at": utc_now(),
            **payload,
        }
        self.db.execute(
            "INSERT INTO notifications(event_id,event_type,listing_key,payload,created_at) VALUES (?,?,?,?,?)",
            (event_id, event_type, listing_key, dumps(payload), utc_now()),
        )
        return event_id

    def all_listings(self, review: bool = False) -> list[dict]:
        data = [
            {**json.loads(row["data"]), "listing_key": row["id"]}
            for row in self.db.execute("SELECT * FROM listings")
        ]
        return [
            item for item in data if not review or item["classification"] == "REVIEW"
        ]

    def ingest(
        self,
        listings: list[Listing],
        config: dict,
        source: str,
        notify_initial: bool = False,
        complete: bool = True,
        baseline_event_id: str | None = None,
        track_availability: bool = True,
    ) -> dict:
        now = utc_now()
        counts = {
            "parsed": len(listings),
            "accepted": 0,
            "review": 0,
            "filtered": 0,
            "events": 0,
        }
        baseline_key = f"baseline:{source}"
        initial = not self.db.execute(
            "SELECT 1 FROM meta WHERE key=?", (baseline_key,)
        ).fetchone()
        summary = []
        with self.db:
            for listing in listings:
                counts[
                    {
                        "ACCEPTED": "accepted",
                        "REVIEW": "review",
                        "REJECTED": "filtered",
                    }[listing.classification]
                ] += 1
                previous = self.db.execute(
                    "SELECT l.* FROM listings l JOIN listing_sources s ON s.listing_key=l.id WHERE s.source=? AND s.listing_id=?",
                    (listing.source, listing.listing_id),
                ).fetchone()
                cross_duplicate = False
                if not previous and listing.verified_identity:
                    previous = self.db.execute(
                        "SELECT * FROM listings WHERE verified_identity=?",
                        (listing.verified_identity,),
                    ).fetchone()
                    cross_duplicate = previous is not None
                if not previous:
                    references = {
                        canonical_url(url)
                        for url in [listing.canonical_url, *listing.source_urls]
                    }
                    for candidate in self.db.execute(
                        "SELECT * FROM listings"
                    ).fetchall():
                        existing = json.loads(candidate["data"])
                        other_references = {
                            canonical_url(url)
                            for url in [
                                existing["canonical_url"],
                                *existing["source_urls"],
                            ]
                        }
                        if references.intersection(other_references):
                            previous = candidate
                            cross_duplicate = True
                            break
                if cross_duplicate:
                    old = json.loads(previous["data"])
                    old["source_urls"] = list(
                        dict.fromkeys(
                            [
                                *old["source_urls"],
                                *listing.source_urls,
                                listing.canonical_url,
                            ]
                        )
                    )
                    reappeared = (
                        old["listing_status"] != "ACTIVE"
                        and listing.listing_status == "ACTIVE"
                    )
                    if reappeared:
                        urls = old["source_urls"]
                        old = listing.to_dict()
                        old.update(
                            source_urls=urls,
                            first_seen_utc=previous["first_seen_utc"],
                            last_changed_utc=now,
                        )
                    old["last_seen_utc"] = now
                    # Preserve the representative offer; cross-source differences remain in observations.
                    self.db.execute(
                        "UPDATE listings SET data=?,fingerprint=?,last_seen_utc=?,last_changed_utc=? WHERE id=?",
                        (
                            dumps(old),
                            fingerprint(old),
                            now,
                            old.get("last_changed_utc") or previous["last_changed_utc"],
                            previous["id"],
                        ),
                    )
                    key = previous["id"]
                    for queued in self.db.execute(
                        "SELECT event_id,payload FROM notifications WHERE listing_key=? AND delivery_state='PENDING'",
                        (key,),
                    ).fetchall():
                        payload = json.loads(queued["payload"])
                        if "listing" in payload:
                            payload["listing"]["source_urls"] = old["source_urls"]
                            self.db.execute(
                                "UPDATE notifications SET payload=? WHERE event_id=?",
                                (dumps(payload), queued["event_id"]),
                            )
                    event_type = (
                        self.event_type(listing, previous, config)
                        if reappeared
                        else None
                    )
                    data = old if reappeared else listing.to_dict()
                    digest = fingerprint(data)
                else:
                    data = listing.to_dict()
                    digest = fingerprint(data)
                    data["first_seen_utc"] = (
                        previous["first_seen_utc"] if previous else now
                    )
                    data["last_seen_utc"] = now
                    data["last_changed_utc"] = (
                        previous["last_changed_utc"]
                        if previous and digest == previous["fingerprint"]
                        else now
                    )
                    if previous:
                        old = json.loads(previous["data"])
                        data["source_urls"] = list(
                            dict.fromkeys([*old["source_urls"], *data["source_urls"]])
                        )
                        key = previous["id"]
                        self.db.execute(
                            "UPDATE listings SET data=?,fingerprint=?,last_seen_utc=?,last_changed_utc=?,verified_identity=COALESCE(?,verified_identity) WHERE id=?",
                            (
                                dumps(data),
                                digest,
                                now,
                                data["last_changed_utc"],
                                listing.verified_identity,
                                key,
                            ),
                        )
                    else:
                        cursor = self.db.execute(
                            "INSERT INTO listings(source,listing_id,data,fingerprint,verified_identity,first_seen_utc,last_seen_utc,last_changed_utc) VALUES (?,?,?,?,?,?,?,?)",
                            (
                                listing.source,
                                listing.listing_id,
                                dumps(data),
                                digest,
                                listing.verified_identity,
                                now,
                                now,
                                now,
                            ),
                        )
                        key = cursor.lastrowid
                        # A similar bike is a suggestion, never silently merged.
                        for other in self.db.execute(
                            "SELECT id,data FROM listings WHERE id<>?", (key,)
                        ).fetchall():
                            candidate = json.loads(other["data"])
                            if (
                                listing.model
                                and candidate.get("model") == listing.model
                                and listing.model_year is not None
                                and candidate.get("model_year") == listing.model_year
                                and listing.seller_name
                                and candidate.get("seller_name") == listing.seller_name
                            ):
                                self.db.execute(
                                    "INSERT OR IGNORE INTO duplicate_candidates(listing_key,other_key,reason) VALUES (?,?,?)",
                                    (
                                        key,
                                        other["id"],
                                        "Same model/year/seller; possible relisting, requires identity review",
                                    ),
                                )
                    event_type = self.event_type(listing, previous, config)
                self.db.execute(
                    "INSERT INTO listing_sources VALUES (?,?,?,?) ON CONFLICT(source,listing_id) DO UPDATE SET url=excluded.url",
                    (listing.source, listing.listing_id, key, listing.canonical_url),
                )
                self.db.execute(
                    "INSERT INTO source_availability(source,listing_id,status) VALUES (?,?,?) ON CONFLICT(source,listing_id) DO UPDATE SET missed_scans=0,last_missing_utc=NULL,status=excluded.status",
                    (listing.source, listing.listing_id, listing.listing_status),
                )
                self.db.execute(
                    "INSERT INTO observations(listing_key,observed_at,asking_price_nzd,odometer_km,listing_status,fingerprint,provenance,data) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        key,
                        now,
                        listing.asking_price_nzd,
                        listing.odometer_km,
                        listing.listing_status,
                        digest,
                        dumps(listing.evidence.get("fetch", {})),
                        dumps(data),
                    ),
                )
                if (
                    listing.classification in {"ACCEPTED", "REVIEW"}
                    and not cross_duplicate
                ):
                    context = self.alert_payload(data, "BASELINE_SUMMARY", config)
                    summary.append(
                        {
                            **data,
                            "changeover": context["changeover"],
                            "model_support": context["model_support"],
                        }
                    )
                suppressed = initial and not (
                    notify_initial or config["alerts"]["notify_initial_results"]
                )
                if event_type and not suppressed:
                    payload = self.alert_payload(data, event_type, config)
                    if event_type == "PRICE_DROP" and previous:
                        reference = previous["last_event_price"]
                        reduction = reference - listing.asking_price_nzd
                        payload["price_change"] = {
                            "previous_notified_price_nzd": reference,
                            "reduction_nzd": reduction,
                            "reduction_percent": round(reduction * 100 / reference, 2),
                        }
                        payload["reason"] = (
                            f"Asking/buy-now price fell NZ${reduction} from NZ${reference}"
                        )
                    self.enqueue(event_type, key, payload)
                    counts["events"] += 1
                # Anchor price to the last queued notification, or initial baseline.
                # Stable pending events count as notified intentions; MQTT retry cannot create new ones.
                if (
                    (event_type and not suppressed or initial)
                    and listing.classification == "ACCEPTED"
                    and (not cross_duplicate or event_type == "LISTING_REACTIVATED")
                ):
                    self.db.execute(
                        "UPDATE listings SET last_event_price=? WHERE id=?",
                        (listing.asking_price_nzd, key),
                    )
            if complete and track_availability:
                counts["unavailable"] = self.update_availability(
                    source, listings, config, now
                )
            if initial and complete:
                if not (notify_initial or config["alerts"]["notify_initial_results"]):
                    payload = {
                        "source": source,
                        "counts": counts.copy(),
                        "listings": summary,
                        "reason": "First successful collection baseline",
                    }
                    if baseline_event_id:
                        existing = self.db.execute(
                            "SELECT payload FROM notifications WHERE event_id=?",
                            (baseline_event_id,),
                        ).fetchone()
                        if existing:
                            payload = json.loads(existing[0])
                            payload.setdefault("sources", {})[source] = counts.copy()
                            payload["listings"].extend(summary)
                            self.db.execute(
                                "UPDATE notifications SET payload=? WHERE event_id=?",
                                (dumps(payload), baseline_event_id),
                            )
                        else:
                            payload.update(
                                schema_version=1,
                                event_id=baseline_event_id,
                                event_type="BASELINE_SUMMARY",
                                listing_key=None,
                                observed_at=now,
                                sources={source: counts.copy()},
                            )
                            self.db.execute(
                                "INSERT INTO notifications(event_id,event_type,payload,created_at) VALUES (?,?,?,?)",
                                (
                                    baseline_event_id,
                                    "BASELINE_SUMMARY",
                                    dumps(payload),
                                    now,
                                ),
                            )
                            counts["events"] += 1
                    else:
                        self.enqueue("BASELINE_SUMMARY", None, payload)
                        counts["events"] += 1
                self.db.execute("INSERT INTO meta VALUES (?,?)", (baseline_key, now))
        return counts

    def update_availability(
        self, source: str, seen: list[Listing], config: dict, now: str
    ) -> int:
        """Absence is inferred only from complete scans with an unchanged search scope."""
        settings = config.get("availability", {})
        threshold = settings.get("missing_scans", 2)
        interval = settings.get("minimum_hours_between_misses", 12)
        scope = hashlib.sha256(
            dumps(
                {
                    "options": config["search"]["sources"].get(source),
                    "models": config["search"]["models"],
                }
            ).encode()
        ).hexdigest()
        key = f"availability_scope:{source}"
        old_scope = self.db.execute(
            "SELECT value FROM meta WHERE key=?", (key,)
        ).fetchone()
        self.db.execute(
            "INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, scope),
        )
        if not old_scope or old_scope[0] != scope:
            self.db.execute(
                "UPDATE source_availability SET missed_scans=0,last_missing_utc=NULL WHERE source=?",
                (source,),
            )
            return 0
        identities = {item.listing_id for item in seen}
        affected = set()
        for row in self.db.execute(
            "SELECT a.*,s.listing_key FROM source_availability a JOIN listing_sources s USING(source,listing_id) WHERE a.source=?",
            (source,),
        ).fetchall():
            if row["listing_id"] in identities:
                continue
            if (
                row["last_missing_utc"]
                and (
                    datetime.fromisoformat(now)
                    - datetime.fromisoformat(row["last_missing_utc"])
                ).total_seconds()
                < interval * 3600
            ):
                continue
            misses = row["missed_scans"] + 1
            state = "UNKNOWN" if misses >= threshold else row["status"]
            self.db.execute(
                "UPDATE source_availability SET missed_scans=?,last_missing_utc=?,status=? WHERE source=? AND listing_id=?",
                (misses, now, state, source, row["listing_id"]),
            )
            affected.add(row["listing_key"])
        changed = 0
        for listing_key in affected:
            states = [
                row[0]
                for row in self.db.execute(
                    "SELECT a.status FROM source_availability a JOIN listing_sources s USING(source,listing_id) WHERE s.listing_key=?",
                    (listing_key,),
                )
            ]
            if "ACTIVE" in states:
                continue
            row = self.db.execute(
                "SELECT * FROM listings WHERE id=?", (listing_key,)
            ).fetchone()
            data = json.loads(row["data"])
            if data["listing_status"] != "ACTIVE":
                continue
            data["listing_status"] = "UNKNOWN"
            data["last_changed_utc"] = now
            data["evidence"]["availability"] = {
                "status": "NOT_SEEN",
                "observed_at": now,
                "reason": f"Absent from at least {threshold} complete, spaced scans on every recorded source; no longer seen available, sale not confirmed",
            }
            digest = fingerprint(data)
            self.db.execute(
                "UPDATE listings SET data=?,fingerprint=?,last_changed_utc=? WHERE id=?",
                (dumps(data), digest, now, listing_key),
            )
            self.db.execute(
                "INSERT INTO observations(listing_key,observed_at,asking_price_nzd,odometer_km,listing_status,fingerprint,provenance,data) VALUES (?,?,?,?,?,?,?,?)",
                (
                    listing_key,
                    now,
                    data["asking_price_nzd"],
                    data["odometer_km"],
                    "UNKNOWN",
                    digest,
                    dumps({"adapter": "absence_tracking", "source": source}),
                    dumps(data),
                ),
            )
            if data["classification"] in {"ACCEPTED", "REVIEW"}:
                self.enqueue(
                    "LISTING_UNAVAILABLE",
                    listing_key,
                    self.alert_payload(
                        data, data["evidence"]["availability"]["reason"], config
                    ),
                )
            changed += 1
        return changed

    @staticmethod
    def event_type(
        listing: Listing, previous: sqlite3.Row | None, config: dict
    ) -> str | None:
        if listing.classification == "REJECTED" or listing.listing_status != "ACTIVE":
            return None
        old = json.loads(previous["data"]) if previous else None
        if old and old.get("listing_status") in {"ENDED", "UNKNOWN"}:
            return "LISTING_REACTIVATED"
        if listing.classification == "REVIEW":
            if config["alerts"]["notify_unknown_power"] and (
                not old
                or old["classification"] != "REVIEW"
                or old["rejection_reasons"] != listing.rejection_reasons
            ):
                return "REVIEW_REQUIRED"
            return None
        if not old or old["classification"] != "ACCEPTED":
            return "NEW_LISTING"
        reference = previous["last_event_price"]
        price = listing.asking_price_nzd
        if reference is not None and price is not None:
            threshold = min(
                config["alerts"]["price_drop_nzd"],
                reference * config["alerts"]["price_drop_percent"] / 100,
            )
            if reference - price >= threshold:
                return "PRICE_DROP"
        return None

    def alert_payload(self, data: dict, reason: str, config: dict) -> dict:
        support = self.db.execute(
            "SELECT data FROM model_support WHERE model=?", (data.get("model"),)
        ).fetchone()
        scenarios = config.get("changeover", {}).get("scenarios", {})
        scenario_key = (
            "dealer:" + (data.get("dealer_name") or "")
            if data.get("seller_type") == "DEALER"
            else "private"
            if data.get("seller_type") == "PRIVATE"
            else "unknown"
        )
        scenario = scenarios.get(scenario_key, {})
        valuation = None
        if scenario.get("kind") in {"trade_in", "private_sale"}:
            table = (
                "trade_in_quotes"
                if scenario["kind"] == "trade_in"
                else "private_sale_estimates"
            )
            row = self.db.execute(
                f"SELECT data FROM {table} WHERE id=?", (scenario.get("valuation_id"),)
            ).fetchone()
            valuation = json.loads(row[0]) if row else None
        return {
            "listing": data,
            "reason": reason
            if reason != "REVIEW_REQUIRED"
            else "; ".join(data["rejection_reasons"]),
            "model_support": json.loads(support[0]) if support else None,
            "changeover": changeover(data, valuation, scenario.get("expenses_nzd")),
        }

    def record_run(
        self, source: str, started: str, outcome: str, details: dict
    ) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO collection_runs(started_at,finished_at,adapter,outcome,details) VALUES (?,?,?,?,?)",
                (started, utc_now(), source, outcome, dumps(details)),
            )
            if outcome == "ERROR":
                self.db.execute(
                    "UPDATE source_availability SET missed_scans=0,last_missing_utc=NULL WHERE source=?",
                    (source,),
                )
            # One event for a consecutive error episode, no daily error flood.
            previous = self.db.execute(
                "SELECT outcome FROM collection_runs WHERE adapter=? ORDER BY id DESC LIMIT 1 OFFSET 1",
                (source,),
            ).fetchone()
            if outcome == "ERROR" and previous and previous[0] == "ERROR":
                marker = f"error_episode:{source}"
                if not self.db.execute(
                    "SELECT 1 FROM meta WHERE key=?", (marker,)
                ).fetchone():
                    self.enqueue(
                        "SYSTEM_ERROR",
                        None,
                        {
                            "source": source,
                            "reason": details.get("error"),
                            "fallback": "Native saved-search alerts or manual JSON import",
                        },
                    )
                    self.db.execute(
                        "INSERT INTO meta VALUES (?,?)", (marker, utc_now())
                    )
            if outcome == "SUCCESS":
                self.db.execute(
                    "DELETE FROM meta WHERE key=?", (f"error_episode:{source}",)
                )

    def history(self, identity: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT o.* FROM observations o JOIN listing_sources s ON o.listing_key=s.listing_key WHERE s.listing_id=? OR (s.source || ':' || s.listing_id)=? GROUP BY o.id ORDER BY o.id",
            (identity, identity),
        )
        return [
            dict(row)
            | {
                "data": json.loads(row["data"]),
                "provenance": json.loads(row["provenance"]),
            }
            for row in rows
        ]

    def status(self) -> dict:
        return {
            "listings": self.db.execute("SELECT count(*) FROM listings").fetchone()[0],
            "pending_events": self.db.execute(
                "SELECT count(*) FROM notifications WHERE delivery_state='PENDING'"
            ).fetchone()[0],
            "runs": [
                dict(row) | {"details": json.loads(row["details"])}
                for row in self.db.execute(
                    "SELECT * FROM collection_runs ORDER BY id DESC LIMIT 10"
                )
            ],
            "possible_duplicates": [
                dict(row)
                for row in self.db.execute(
                    "SELECT * FROM duplicate_candidates WHERE state='REVIEW'"
                )
            ],
        }
