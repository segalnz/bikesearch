"""Human-readable saved results; the JSON interface remains available."""

from datetime import datetime
from zoneinfo import ZoneInfo


def show_listings(listings: list[dict]) -> None:
    if not listings:
        print("No matching or review listings saved yet.")
        return
    for item in listings:
        evidence = item.get("evidence", {}).get("availability", {})
        state = (
            "NO LONGER SEEN AVAILABLE"
            if item["listing_status"] == "UNKNOWN"
            and evidence.get("status") == "NOT_SEEN"
            else {
                "ACTIVE": "AVAILABLE",
                "ENDED": "ENDED",
                "UNKNOWN": "AVAILABILITY UNKNOWN",
            }[item["listing_status"]]
        )
        print(f"\n[{state}] [{item['classification']}] {item['title']}")
        price = item.get("asking_price_nzd")
        price_text = f"NZ${price:,}" if price is not None else "unknown"
        odo = item.get("odometer_km")
        odo_text = f"{odo:,} km" if odo is not None else "unknown mileage"
        print(
            f"  {item.get('model_year') or 'Year unknown'} | {price_text} ({item['price_type']}) | {odo_text}"
        )
        print(
            f"  {item.get('location') or 'Location unknown'} | {item.get('dealer_name') or item.get('seller_name') or 'Seller unknown'}"
        )
        print(
            f"  Power: {item['power_status']} — {item.get('power_evidence') or 'No evidence'}"
        )
        print(f"  Trade-in: {item.get('trade_in_available', 'UNKNOWN')}")
        for reason in item.get("rejection_reasons", []):
            print(f"  Review/filter reason: {reason}")
        if evidence.get("reason") and item["listing_status"] != "ACTIVE":
            print("  Availability: " + evidence["reason"])
        seen = item.get("last_seen_utc")
        if seen:
            print(
                "  Last seen: "
                + datetime.fromisoformat(seen)
                .astimezone(ZoneInfo("Pacific/Auckland"))
                .strftime("%d %b %Y %H:%M %Z")
            )
        cost = item.get("changeover", {})
        if cost.get("changeover_nzd") is not None:
            print(
                f"  Changeover: NZ${cost['changeover_nzd']:,}; assumptions: {cost.get('valuation')}, ORC {cost.get('orc_nzd')}, expenses {cost.get('expenses_nzd')}"
            )
        elif cost.get("unknowns"):
            print("  Changeover unknown: " + ", ".join(cost["unknowns"]))
        for url in item.get("source_urls", []) or [item["canonical_url"]]:
            print("  " + url)
        print(f"  History ID: {item['source']}:{item['listing_id']}")
