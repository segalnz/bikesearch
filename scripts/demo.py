#!/usr/bin/env python3
"""Run an offline showcase with fictional bikes, isolated from live credentials/data."""

import argparse
import tempfile
from copy import deepcopy
from pathlib import Path

import yaml

from motorcycle_monitor.config import DEFAULTS
from motorcycle_monitor.filtering import classify
from motorcycle_monitor.schema import Listing
from motorcycle_monitor.storage import Store
from motorcycle_monitor.web import serve

ROOT = Path(__file__).resolve().parent.parent


def build_demo(folder: Path) -> dict:
    config = deepcopy(DEFAULTS)
    preset = yaml.safe_load((ROOT / "config.bike-search.yaml").read_text())
    config["search"] = deepcopy(preset["search"])
    config["search"]["sources"] = {
        "demo": {
            "enabled": True,
            "allowed_hosts": ["example.com"],
            "search_urls": ["https://example.com/demo"],
        }
    }
    config["database"]["path"] = str(folder / "demo.db")
    config["web"].update(host="127.0.0.1", demo=True, deployment_id="offline-demo")
    folder.mkdir(parents=True, exist_ok=True)
    store = Store(config["database"]["path"])
    try:
        for number, title, description, price, km, location in [
            (
                1,
                "2021 Example Road Twin ABS",
                "Non-LAMS full power. Parallel twin. ABS. Wet weight 205 kg. Seat height 800 mm. 85 hp. Factory screen. English workshop manual included. DIY servicing.",
                10995,
                12000,
                "Lower Hutt, Wellington",
            ),
            (
                2,
                "2018 Example Sport Triple ABS",
                "Full power non-LAMS. Inline triple. ABS. Wet weight 215 kg. Seat height 820 mm. 110 hp. Half fairing. English workshop manual available. DIY servicing.",
                11995,
                22000,
                "Palmerston North, Manawatu",
            ),
            (
                3,
                "2020 Example Four — needs specifications",
                "Non-LAMS full power. Inline four. ABS. 95 hp. Exact wet weight, seat height and workshop support not supplied.",
                9500,
                14000,
                "Christchurch",
            ),
            (
                4,
                "2022 Example Restricted Twin",
                "LAMS learner approved. Parallel twin. ABS.",
                7995,
                5000,
                "Upper Hutt, Wellington",
            ),
        ]:
            listing = Listing(
                "demo",
                str(number),
                f"https://example.com/fictional-bike/{number}",
                title,
                description=description,
                model_year=int(title[:4]),
                asking_price_nzd=price,
                price_type="ASKING",
                odometer_km=km,
                location=location,
                seller_name="Fictional demonstration seller",
                source_urls=[f"https://example.com/fictional-bike/{number}"],
            )
            store.ingest(
                [classify(listing, config)],
                config,
                "demo",
                False,
                track_availability=False,
            )
        store.record_run(
            "demo",
            "2026-01-01T00:00:00+00:00",
            "SUCCESS",
            {
                "parsed": 4,
                "accepted": 2,
                "review": 1,
                "warning": "Offline demonstration: all bikes and prices are fictional.",
            },
        )
    finally:
        store.close()
    config["llm"]["enabled"] = False
    config["mqtt"]["enabled"] = False
    (folder / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-only", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.build_only:
        build_demo(args.build_only)
        print("Offline demo created; all inventory is fictional.")
        return
    with tempfile.TemporaryDirectory(prefix="motorcycle-demo-") as folder:
        config = build_demo(Path(folder))
        print(f"Offline fictional demo: http://127.0.0.1:{args.port}/", flush=True)
        try:
            serve(config, "127.0.0.1", args.port)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
