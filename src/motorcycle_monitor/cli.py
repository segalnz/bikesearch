import argparse
import json
import logging
import sqlite3
import sys
from contextlib import nullcontext
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .filtering import current_criteria, priority
from .normalization import utc_now
from .notifications import MQTTPublisher, drain
from .presentation import show_listings
from .scheduler import scan_lock
from .service import scan
from .storage import Store, dumps
from .trade_in import changeover


def local_times(data: object) -> object:
    if isinstance(data, list):
        return [local_times(item) for item in data]
    if isinstance(data, dict):
        result = {key: local_times(value) for key, value in data.items()}
        for key, value in data.items():
            if isinstance(value, str) and (
                key.endswith("_utc")
                or key in {"observed_at", "started_at", "finished_at"}
            ):
                try:
                    stamp = datetime.fromisoformat(value)
                    if stamp.tzinfo:
                        result[key + "_nz"] = stamp.astimezone(
                            ZoneInfo("Pacific/Auckland")
                        ).isoformat()
                except ValueError:
                    pass
        return result
    return data


def output(data: object) -> None:
    print(json.dumps(local_times(data), indent=2, ensure_ascii=False))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Personal motorcycle monitor (no account or seller automation)"
    )
    root.add_argument("--config", default="config.yaml")
    sub = root.add_subparsers(dest="command", required=True)
    scan_parser = sub.add_parser("scan")
    scan_parser.add_argument("--dry-run", action="store_true")
    scan_parser.add_argument("--notify-initial", action="store_true")
    scan_parser.add_argument(
        "--fresh",
        action="store_true",
        help="Fetch fresh pages instead of reusing the on-disk HTTP cache",
    )
    scan_parser.add_argument(
        "--import-file", help="Manual normalized listing JSON array"
    )
    web = sub.add_parser("serve", help="Serve the read-only desktop dashboard")
    web.add_argument("--host", help="Listen address (default: 0.0.0.0)")
    web.add_argument("--port", type=int, help="Listen port (default: 8765)")
    plan = sub.add_parser(
        "search-plan", help="Display the stored operational search plan"
    )
    plan.add_argument("--json", action="store_true")
    sub.add_parser("status")
    sub.add_parser("validate-config")
    sub.add_parser("test-mqtt")
    sub.add_parser("publish-pending")
    listings = sub.add_parser("listings")
    listings.add_argument("--review", action="store_true")
    listings.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable JSON, including rejected listings",
    )
    listings.add_argument(
        "--all", action="store_true", help="Also display rejected bikes"
    )
    history = sub.add_parser("history")
    history.add_argument("listing_id")
    valuation = sub.add_parser("add-valuation")
    valuation.add_argument("kind", choices=["trade_in", "private_sale"])
    valuation.add_argument("value_nzd", type=int)
    valuation.add_argument("--seller", required=True)
    valuation.add_argument(
        "--basis", choices=["ACTUAL_QUOTE", "ESTIMATE"], required=True
    )
    valuation.add_argument("--date", required=True)
    valuation.add_argument("--expiry")
    valuation.add_argument("--provenance", required=True)
    valuation.add_argument("--notes", default="")
    compare = sub.add_parser("changeover")
    compare.add_argument("listing_id")
    compare.add_argument("--kind", choices=["trade_in", "private_sale"], required=True)
    compare.add_argument("--valuation-id", type=int, required=True)
    compare.add_argument("--expenses-nzd", type=int)
    support = sub.add_parser("model-support")
    support.add_argument(
        "--import-file",
        help="JSON object keyed by model, with memo, sources and last_checked",
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if config["search"].get("mode") == "all_models":
            from .search_plan import read_plan

            config["search"]["_operational_plan"] = read_plan(config) or {}
        handlers = [logging.StreamHandler()]
        if (
            config["logging"]["path"]
            and args.command
            not in {
                "validate-config",
                "status",
                "listings",
                "history",
                "changeover",
                "search-plan",
            }
            and not (args.command == "scan" and args.dry_run)
        ):
            Path(config["logging"]["path"]).parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(config["logging"]["path"]))
        logging.basicConfig(
            level=config["logging"]["level"],
            handlers=handlers,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        if args.command == "serve":
            from .web import serve

            serve(config, args.host, args.port)
            return 0
        if args.command == "validate-config":
            output(
                {
                    "valid": True,
                    "enabled_sources": [
                        k
                        for k, v in config["search"]["sources"].items()
                        if v.get("enabled")
                    ],
                    "warnings": [
                        f"{k}: search URLs required"
                        for k, v in config["search"]["sources"].items()
                        if v.get("enabled") and not v.get("search_urls")
                    ],
                }
            )
            return 0
        if args.command == "search-plan":
            from .search_plan import read_plan

            plan = read_plan(config)
            if args.json:
                output(
                    plan or {"status": "No current plan; the next scan generates one."}
                )
            elif not plan:
                print(
                    "No current operational plan. The next scan generates one when enabled."
                )
            else:
                print(plan["summary"])
                print("\nStored plan: " + plan["generated_at"])
                print("Screening rules are LLM estimates, not verified specifications.")
                for rule in plan["rules"]:
                    print(
                        f"  Screen out {rule['make']} {' / '.join(rule['models'])} ({rule['year_min']}–{rule['year_max']}): expected at most {rule['power_hp_upper']:g} hp. {rule['reason']}"
                    )
                print(
                    "\nPrioritize: "
                    + "; ".join(
                        item["make"] + " " + item["model"]
                        for item in plan["priority_models"]
                    )
                )
                for caution in plan["cautions"]:
                    print("  Note: " + caution)
            return 0
        if args.command == "scan":
            if args.fresh:
                config["collector"]["cache_seconds"] = 0
            result = scan(config, args.dry_run, args.notify_initial, args.import_file)
            output(result)
            return 1 if result["errors"] else 0
        if args.command == "test-mqtt":
            MQTTPublisher(config["mqtt"])(
                config["mqtt"]["topic_prefix"] + "/status",
                dumps(
                    {
                        "schema_version": 1,
                        "event_type": "MQTT_TEST",
                        "event_id": utc_now(),
                        "observed_at": utc_now(),
                        "reason": "Manual MQTT test",
                    }
                ),
            )
            output({"published": True})
            return 0
        path = config["database"]["path"]
        readonly = args.command in {"status", "listings", "history", "changeover"}
        if readonly and not Path(path).exists():
            if args.command == "status":
                output({"initialized": False, "database": path})
                return 0
            raise ValueError("Database does not exist yet; run a scan first")
        with nullcontext() if readonly else scan_lock(path + ".lock"):
            store = Store(path, readonly=readonly)
            try:
                if args.command == "status":
                    result = store.status()
                    result["display_time"] = datetime.now(
                        ZoneInfo("Pacific/Auckland")
                    ).isoformat()
                    output(result)
                elif args.command == "listings":
                    listings = [
                        current_criteria(item, config) for item in store.all_listings()
                    ]
                    if args.review:
                        listings = [
                            item
                            for item in listings
                            if item["classification"] == "REVIEW"
                        ]
                    for listing in listings:
                        listing["changeover"] = store.alert_payload(
                            listing, "COMPARISON", config
                        )["changeover"]
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
                    sorted_listings = sorted(
                        listings,
                        key=lambda item: priority(
                            item
                            if item["ranking_basis"] == "changeover"
                            else {**item, "changeover": {}},
                            config,
                        ),
                    )
                    if args.json:
                        output(sorted_listings)
                    else:
                        show_listings(
                            [
                                item
                                for item in sorted_listings
                                if args.all or item["classification"] != "REJECTED"
                            ]
                        )
                elif args.command == "history":
                    output(store.history(args.listing_id))
                elif args.command == "publish-pending":
                    result = drain(store, config)
                    output(result)
                    return 1 if result["failed"] else 0
                elif args.command == "add-valuation":
                    if args.value_nzd < 0:
                        raise ValueError("Valuation cannot be negative")
                    date.fromisoformat(args.date)
                    if args.expiry:
                        date.fromisoformat(args.expiry)
                    if args.kind == "private_sale" and args.basis == "ACTUAL_QUOTE":
                        raise ValueError(
                            "Private-sale proceeds are estimates; use ESTIMATE"
                        )
                    table = (
                        "trade_in_quotes"
                        if args.kind == "trade_in"
                        else "private_sale_estimates"
                    )
                    data = {
                        "kind": args.kind,
                        "seller": args.seller,
                        "value_nzd": args.value_nzd,
                        "basis": args.basis,
                        "quote_date": args.date,
                        "expiry": args.expiry,
                        "provenance": args.provenance,
                        "notes": args.notes,
                    }
                    with store.db:
                        row = store.db.execute(
                            f"INSERT INTO {table}(data) VALUES (?)", (dumps(data),)
                        )
                    output({"valuation_id": row.lastrowid, **data})
                elif args.command == "changeover":
                    candidates = [
                        x
                        for x in store.all_listings()
                        if x["listing_id"] == args.listing_id
                        or f"{x['source']}:{x['listing_id']}" == args.listing_id
                    ]
                    if len(candidates) != 1:
                        raise ValueError(
                            "Listing absent or ambiguous; use source:listing_id"
                        )
                    table = (
                        "trade_in_quotes"
                        if args.kind == "trade_in"
                        else "private_sale_estimates"
                    )
                    row = store.db.execute(
                        f"SELECT data FROM {table} WHERE id=?", (args.valuation_id,)
                    ).fetchone()
                    if not row:
                        raise ValueError("Valuation not found")
                    if args.expenses_nzd is not None and args.expenses_nzd < 0:
                        raise ValueError("Expenses cannot be negative")
                    output(
                        changeover(candidates[0], json.loads(row[0]), args.expenses_nzd)
                    )
                elif args.command == "model-support":
                    if args.import_file:
                        data = json.loads(Path(args.import_file).read_text())
                        with store.db:
                            for model, memo in data.items():
                                if (
                                    model not in {"Ninja 650", "GSX-8R"}
                                    or not memo.get("sources")
                                    or not memo.get("last_checked")
                                    or not memo.get("memo")
                                ):
                                    raise ValueError(
                                        "Support memo requires configured model, sources, last_checked and memo"
                                    )
                                date.fromisoformat(memo["last_checked"])
                                store.db.execute(
                                    "INSERT INTO model_support VALUES (?,?) ON CONFLICT(model) DO UPDATE SET data=excluded.data",
                                    (model, dumps(memo)),
                                )
                    output(
                        {
                            r["model"]: json.loads(r["data"])
                            for r in store.db.execute("SELECT * FROM model_support")
                        }
                    )
            finally:
                store.close()
        return 0
    except (
        ValueError,
        OSError,
        RuntimeError,
        KeyError,
        TypeError,
        sqlite3.Error,
    ) as error:
        print(f"motorcycle-monitor: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
