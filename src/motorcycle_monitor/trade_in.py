"""Manual valuations with explicit unknown costs and provenance."""

from datetime import date, datetime
from zoneinfo import ZoneInfo


def changeover(
    listing: dict, valuation: dict | None, expenses_nzd: int | None = None
) -> dict:
    unknowns = []
    price = (
        listing.get("asking_price_nzd")
        if listing.get("price_type") in {"ASKING", "BUY_NOW"}
        else None
    )
    orc = listing.get("orc_nzd")
    if price is None:
        unknowns.append("fixed asking price")
    if orc is None:
        unknowns.append("on-road costs")
    if expenses_nzd is None:
        unknowns.append("travel/delivery/other expenses")
    if valuation is None:
        unknowns.append("trade-in allowance or net private-sale proceeds")
    elif (
        valuation.get("expiry")
        and date.fromisoformat(valuation["expiry"])
        < datetime.now(ZoneInfo("Pacific/Auckland")).date()
    ):
        unknowns.append("valuation expired")
    if (
        valuation
        and listing.get("seller_type") == "DEALER"
        and valuation.get("kind") == "trade_in"
    ):
        if valuation.get("seller") != listing.get("dealer_name"):
            unknowns.append("trade-in quote is for a different dealer")
        if listing.get("trade_in_available") != "YES":
            unknowns.append("trade-in availability unverified")
    return {
        "changeover_nzd": None
        if unknowns
        else price + orc + expenses_nzd - valuation["value_nzd"],
        "formula": "asking + ORC + purchase expenses - allowance/net sale proceeds",
        "asking_price_nzd": price,
        "orc_nzd": orc,
        "expenses_nzd": expenses_nzd,
        "valuation": valuation,
        "unknowns": unknowns,
    }
