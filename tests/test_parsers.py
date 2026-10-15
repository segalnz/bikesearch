from pathlib import Path

import pytest

from motorcycle_monitor.config import load_config
from motorcycle_monitor.filtering import classify
from motorcycle_monitor.parsers import ParseError, parse

F = Path(__file__).parent / "fixtures"


def test_synthetic_structured(config):
    result = parse(
        (F / "structured.html").read_text(),
        "https://www.trademe.co.nz/search",
        "trademe",
        config["search"]["sources"]["trademe"],
    )
    assert len(result) == 1
    assert result[0].odometer_km == 8500
    assert classify(result[0], config).classification == "ACCEPTED"


@pytest.mark.parametrize(
    "html",
    [
        "<html>Page changed</html>",
        "Access denied",
        "verify you are human",
        '<script type="application/ld+json">oops</script>',
    ],
)
def test_faulty_page_is_not_zero(html, config):
    with pytest.raises(ParseError):
        parse(
            html,
            "https://www.trademe.co.nz/search",
            "trademe",
            config["search"]["sources"]["trademe"],
        )


def test_foreign_currency_unknown(config):
    html = (F / "structured.html").read_text().replace('"NZD"', '"USD"')
    assert (
        parse(
            html,
            "https://www.trademe.co.nz/search",
            "trademe",
            config["search"]["sources"]["trademe"],
        )[0].asking_price_nzd
        is None
    )


def test_actual_dealer_excerpts():
    c = load_config("config.example.yaml")
    for name, title, price, odo in [
        ("tss", "Husqvarna Svartpilen", 9995, 4729),
        ("cyclespot", "Aprilia Tuono V4 Factory  2022", 18495, 34100),
    ]:
        source = "dealer_" + name
        opts = c["search"]["sources"][source]
        html = (F / f"{name}-0.html").read_text()
        if name == "cyclespot":
            html = '<div id="listCars">' + html + "</div>"
        listing = parse(html, opts["search_urls"][0], source, opts)[0]
        assert listing.title == title
        assert listing.asking_price_nzd == price
        assert listing.odometer_km == odo
        assert listing.seller_type == "DEALER"
        assert listing.trade_in_available == "UNKNOWN"


def test_actual_trademe_searches():
    c = load_config("config.example.yaml")
    o = c["search"]["sources"]["trademe"]
    ninja = parse(
        (F / "trademe-ninja.html").read_text(), o["search_urls"][0], "trademe", o
    )
    assert len(ninja) == 18
    assert ninja[2].asking_price_nzd == 11899
    assert classify(ninja[0], c).classification == "REJECTED"
    assert classify(ninja[2], c).classification == "ACCEPTED"
    gsx = parse((F / "trademe-gsx.html").read_text(), o["search_urls"][1], "trademe", o)
    assert len(gsx) == 9
    assert gsx[-1].price_type == "BUY_NOW"
    assert gsx[-1].asking_price_nzd == 15999


def test_actual_trademe_detail():
    c = load_config("config.example.yaml")
    o = {**c["search"]["sources"]["trademe"], "parser": "trademe_detail"}
    url = "https://www.trademe.co.nz/a/motors/motorbikes/motorbikes/sports/kawasaki/listing/5915854398?rsqid=original"
    listing = parse((F / "trademe-detail.html").read_text(), url, "trademe", o)[0]
    assert listing.canonical_url == url
    assert listing.asking_price_nzd == 11899
    assert listing.seller_name == "AFC Motorcycles"
    assert listing.orc_nzd is None
    assert classify(listing, c).classification == "ACCEPTED"


def test_detail_offer_without_fixed_label_is_unknown():
    c = load_config("config.example.yaml")
    o = {**c["search"]["sources"]["trademe"], "parser": "trademe_detail"}
    html = (
        (F / "trademe-detail.html").read_text().replace("Asking price", "Current bid")
    )
    url = "https://www.trademe.co.nz/a/motors/motorbikes/motorbikes/sports/kawasaki/listing/5915854398"
    listing = parse(html, url, "trademe", o)[0]
    assert listing.asking_price_nzd is None
    assert classify(listing, c).classification == "REVIEW"


def test_explicit_zero_cyclespot():
    c = load_config("config.example.yaml")
    o = c["search"]["sources"]["dealer_cyclespot"]
    assert (
        parse(
            '<div class="car-count-details">Showing 0 vehicles available</div>',
            o["search_urls"][0],
            "dealer_cyclespot",
            o,
        )
        == []
    )


def test_actual_cyclespot_new_stock():
    c = load_config("config.example.yaml")
    o = c["search"]["sources"]["dealer_cyclespot"]
    listings = parse(
        (F / "cyclespot-new.html").read_text(),
        o["search_urls"][1],
        "dealer_cyclespot",
        o,
    )
    assert len(listings) == 9
    html = (
        (F / "cyclespot-new.html")
        .read_text()
        .replace("Showing 9 vehicles available", "Showing 20 vehicles available")
    )
    with pytest.raises(ParseError, match="inventory count"):
        parse(html, o["search_urls"][1], "dealer_cyclespot", o)


def test_target_model_in_actual_search_subtitle():
    c = load_config("config.example.yaml")
    o = c["search"]["sources"]["trademe"]
    listings = parse(
        (F / "trademe-ninja.html").read_text(), o["search_urls"][0], "trademe", o
    )
    listing = next(item for item in listings if "SALE ON NOW" in item.title)
    assert listing.model == "Ninja 650"
    assert classify(listing, c).classification == "ACCEPTED"
