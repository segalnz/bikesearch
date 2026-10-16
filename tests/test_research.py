import copy
import json

import httpx
import pytest

from motorcycle_monitor.filtering import classify
from motorcycle_monitor.research import ModelResearcher, source_host, validate_facts
from motorcycle_monitor.schema import Listing


def bike():
    return Listing(
        source="trademe",
        listing_id="1",
        canonical_url="https://www.trademe.co.nz/listing/1",
        title="2020 Kawasaki Ninja 650",
        model_year=2020,
        description="Full power, non-LAMS",
        asking_price_nzd=10000,
        price_type="ASKING",
        odometer_km=10000,
    )


DOCS = [
    {
        "url": "https://www.kawasaki.eu/2020/ninja650.html",
        "text": "2020 Kawasaki Ninja 650. Maximum power 50.2 kW. Curb weight 193 kg. Seat height 790 mm. ABS is standard. 2 cylinders.",
    }
]
FACT = {
    "field": "power_hp",
    "value": 67.32,
    "source": 0,
    "model_quote": "Kawasaki Ninja 650",
    "year_quote": "2020 Kawasaki Ninja 650",
    "quotation": "Maximum power 50.2 kW",
}


def test_researched_low_power_is_excluded_without_advert_power(broad_config):
    item = bike()
    item.evidence["model_research"] = {
        "facts": validate_facts({"facts": [FACT]}, DOCS, item)
    }
    assert classify(item, broad_config).classification == "REJECTED"
    assert any("below required 80" in reason for reason in item.rejection_reasons)
    fact = item.evidence["suitability"]["facts"]["power_hp"]
    assert fact["source_url"] == DOCS[0]["url"]


@pytest.mark.parametrize(
    "changes",
    [
        {"quotation": "Maximum power 90 hp", "value": 90},
        {"year_quote": "2021 Kawasaki Ninja 650"},
        {"model_quote": "Kawasaki"},
        {"source": True},
        {"source": 5},
        {"field": "wet_weight_kg", "value": 193, "quotation": "Maximum power 50.2 kW"},
        {"field": "abs", "value": True, "quotation": "2 cylinders."},
        {"field": "english_manual", "value": True, "quotation": "ABS is standard."},
    ],
)
def test_unsupported_model_facts_are_discarded(changes):
    assert not validate_facts({"facts": [{**FACT, **changes}]}, DOCS, bike())


def test_wrong_year_model_cannot_satisfy_requirements():
    item = bike()
    item.model_year = 2021
    assert not validate_facts({"facts": [FACT]}, DOCS, item)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.kawasaki.eu/a",
        "https://kawasaki.eu.evil.example/a",
        "https://127.0.0.1/a",
        "https://www.kawasaki.eu:444/a",
        "https://user:secret@www.kawasaki.eu/a",
    ],
)
def test_model_cannot_fetch_arbitrary_hosts_or_credentials(url):
    with pytest.raises(ValueError):
        source_host(url)


def test_researched_low_power_excludes_even_when_seller_claims_more(broad_config):
    item = bike()
    item.description += " 100 hp"
    item.evidence["model_research"] = {
        "facts": validate_facts({"facts": [FACT]}, DOCS, item)
    }
    classify(item, broad_config)
    assert item.classification == "REJECTED"
    assert item.evidence["suitability"]["facts"]["power_hp"]["value"] < 80


class Pages:
    requests = 0

    def get(self, url, hosts):
        self.requests += 1
        if hosts == ["www.bing.com"]:
            return (
                "<rss><channel><item><link>"
                + DOCS[0]["url"]
                + "</link></item><item><link>https://127.0.0.1/secret</link></item></channel></rss>"
            )
        assert url == DOCS[0]["url"]
        return "<html><body>" + DOCS[0]["text"] + "</body></html>"


def response(request):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"facts": [FACT]})},
                }
            ]
        },
    )


def test_search_fetch_extract_cache_and_reclassify(tmp_path, monkeypatch, broad_config):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        "motorcycle_monitor.research_sources.document_urls", lambda listing: []
    )
    client = httpx.Client(transport=httpx.MockTransport(response))
    pages = Pages()
    options = {
        "api_key_file": "unused",
        "model": "deepseek-flash",
        "research_calls_per_scan": 1,
    }
    researcher = ModelResearcher(options, pages, tmp_path, client)
    item = bike()
    researcher.research(item)
    assert item.evidence["model_research"]["status"] == "researched"
    assert researcher.calls == 1
    assert classify(item, broad_config).classification == "REJECTED"
    before = pages.requests
    duplicate = bike()
    duplicate.listing_id = "2"
    researcher.research(duplicate)
    assert pages.requests == before
    # New process can reuse model findings without another paid call.
    second = ModelResearcher(options, pages, tmp_path, client)
    second.research(bike())
    assert pages.requests == before
    assert second.calls == 0
    client.close()


def test_exhausted_budget_never_fetches_or_fabricates():
    researcher = ModelResearcher({"research_calls_per_scan": 1}, Pages())
    researcher.calls = 1
    item = bike()
    researcher.research(item)
    assert item.evidence["model_research"]["status"] == "pending"
    assert researcher.fetcher.requests == 0
    researcher.close()


def test_unknown_power_requires_review_and_exact_boundary(broad_config):
    item = bike()
    classify(item, broad_config)
    assert any("80 hp mandatory" in reason for reason in item.rejection_reasons)
    item.description += " 79.9 hp"
    classify(item, broad_config)
    assert item.classification == "REJECTED"
    item.description = item.description.replace("79.9 hp", "80 hp")
    classify(item, broad_config)
    assert not any("below required" in reason for reason in item.rejection_reasons)


def test_optional_power_preference_remains_supported(broad_config):
    config = copy.deepcopy(broad_config)
    del config["search"]["requirements"]["min_power_hp"]
    item = bike()
    item.description += " 70 hp"
    classify(item, config)
    assert not any("below required" in reason for reason in item.rejection_reasons)


def test_power_is_calculated_from_source_units_not_model_guess():
    facts = validate_facts({"facts": [{**FACT, "value": 68}]}, DOCS, bike())
    assert facts["power_hp"]["value"] == 67.32


def test_multi_model_numeric_rows_cannot_establish_weight():
    docs = [{**DOCS[0], "text": DOCS[0]["text"] + " Curb mass 206 kg 196 kg 193 kg"}]
    claim = {
        **FACT,
        "field": "wet_weight_kg",
        "value": 193,
        "quotation": "Curb mass 206 kg 196 kg 193 kg",
    }
    assert not validate_facts({"facts": [claim]}, docs, bike())


def test_reviewed_brochure_association_excludes_ninja_without_cloud_guess(broad_config):
    from motorcycle_monitor.research_sources import KAWASAKI, indexed_claims

    item = bike()
    docs = [
        {
            "url": KAWASAKI[2020],
            "text": "2020 NINJA Specifications. Ninja 650. Maximum power 50.2 kW {68 PS}.",
        }
    ]
    claims = indexed_claims(item, docs)
    facts = validate_facts({"facts": claims}, docs, item)
    assert facts["power_hp"]["value"] == 67.32
    item.evidence["model_research"] = {"facts": facts}
    assert classify(item, broad_config).classification == "REJECTED"
    docs[0]["text"] = docs[0]["text"].replace("50.2 kW", "different specification")
    assert not indexed_claims(item, docs)


def test_uncached_source_budget_does_not_starve_later_scans(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "motorcycle_monitor.research_sources.document_urls", lambda listing: []
    )

    class NoDocuments:
        requests = 0

        def get(self, url, hosts):
            self.requests += 1
            return "<rss><channel></channel></rss>"

    pages = NoDocuments()
    researcher = ModelResearcher({}, pages, tmp_path)
    for i in range(5):
        item = bike()
        item.title = f"2020 Example Model {i}"
        researcher.research(item)
    assert item.evidence["model_research"]["status"] == "pending"
    assert researcher.source_attempts == 4
    later = ModelResearcher({}, pages, tmp_path)
    for i in range(5):
        item = bike()
        item.title = f"2020 Example Model {i}"
        later.research(item)
    assert later.source_attempts == 1
    assert item.evidence["model_research"]["status"] == "unknown"
    researcher.close()
    later.close()


@pytest.mark.parametrize(
    "title,year", [("Kawasaki Ninja ZX6R 2026", 2026), ("Yamaha Xsr900 2020", 2020)]
)
def test_reviewed_seat_height_excludes_stock_shortlist_near_misses(
    broad_config, title, year
):
    item = bike()
    item.title = title
    item.model_year = year
    classify(item, broad_config)
    assert item.classification == "REJECTED"
    fact = item.evidence["suitability"]["facts"]["seat_height_mm"]
    assert fact["value"] == 830 and fact["reviewed_reference"]
    assert fact["source_url"].startswith("https://")
    assert "Seat height exceeds maximum" in item.rejection_reasons


@pytest.mark.parametrize(
    "title,year",
    [
        ("Yamaha XSR900 2022", 2022),
        ("Yamaha XSR900 2020", 2021),
        ("Honda XSR900 2020", 2020),
    ],
)
def test_reference_never_crosses_model_year_or_manufacturer(broad_config, title, year):
    item = bike()
    item.title = title
    item.model_year = year
    classify(item, broad_config)
    assert "seat_height_mm" not in item.evidence["suitability"]["facts"]


def test_modified_or_explicitly_lower_seat_requires_review(broad_config):
    for claim in ["Lowered seat", "Seat height 800 mm", "Lowering links fitted"]:
        item = bike()
        item.title = "Yamaha XSR900 2020"
        item.description = claim
        classify(item, broad_config)
        assert item.classification == "REVIEW"


def test_llm_source_fallback_resolves_power_when_search_is_empty(tmp_path, monkeypatch):
    from motorcycle_monitor.research import EXTRACT, LOCATE

    monkeypatch.setattr(
        "motorcycle_monitor.research_sources.document_urls", lambda item: []
    )
    options = {"research_calls_per_scan": 3}
    researcher = ModelResearcher(options, Pages(), tmp_path)
    monkeypatch.setattr(researcher, "discover", lambda query: [])
    calls = []

    def chat(system, context):
        calls.append(system)
        if system == LOCATE:
            return {
                "power_hp_estimate": 999,
                "sources": ["https://127.0.0.1/private", DOCS[0]["url"]],
            }
        assert system == EXTRACT
        return {"facts": [FACT]}

    monkeypatch.setattr(researcher, "chat", chat)
    item = bike()
    researcher.research(item)
    fact = item.evidence["model_research"]["facts"]["power_hp"]
    assert calls == [LOCATE, EXTRACT]
    assert fact["value"] == 67.32  # Quoted kW conversion, never the guessed 999.
    assert fact["source_url"] == DOCS[0]["url"]
    duplicate = bike()
    researcher.research(duplicate)
    assert calls == [LOCATE, EXTRACT]
    researcher.close()


def test_unverifiable_llm_power_never_becomes_fact(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "motorcycle_monitor.research_sources.document_urls", lambda item: []
    )
    researcher = ModelResearcher({}, Pages(), tmp_path)
    monkeypatch.setattr(researcher, "discover", lambda query: [])
    monkeypatch.setattr(
        researcher,
        "chat",
        lambda *args: {
            "power_hp_estimate": 120,
            "sources": ["https://127.0.0.1/private"],
        },
    )
    item = bike()
    researcher.research(item)
    assert item.evidence["model_research"]["facts"] == {}
    assert researcher.fetcher.requests == 0
    researcher.close()


@pytest.mark.parametrize("model,power", [("675 NK", 93.9), ("500 SR VOOM", 77.8)])
def test_current_nz_power_references_are_visible_and_scoped(broad_config, model, power):
    item = bike()
    item.title = "2026 CFMOTO " + model
    item.model_year = 2026
    classify(item, broad_config)
    fact = item.evidence["suitability"]["facts"]["power_hp"]
    assert fact["value"] == power
    assert fact["source_url"].startswith("https://www.cfmoto.co.nz/model/")
    if power < 80:
        assert item.classification == "REJECTED"
    item.model_year = 2024
    classify(item, broad_config)
    assert "power_hp" not in item.evidence["suitability"]["facts"]
