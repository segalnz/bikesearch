import copy
import json

import httpx
import pytest

from motorcycle_monitor.filtering import classify
from motorcycle_monitor.schema import Listing
from motorcycle_monitor.search_plan import (
    compile_plan,
    model_matches,
    policy_fingerprint,
    read_plan,
    screen,
    validate_plan,
)

RAW = {
    "summary": "Screen low-powered families and prioritize suitable road bikes; preserve 600 cc four-cylinder exceptions.",
    "rules": [
        {
            "name": "Kawasaki road twin",
            "make": "Kawasaki",
            "models": ["Ninja 650", "Z650"],
            "year_min": 2017,
            "year_max": 2027,
            "action": "screen_out",
            "confidence": "high",
            "power_hp_upper": 72,
            "reason": "Stock full-power family below 80 hp.",
        }
    ],
    "priority_models": [
        {
            "make": "Honda",
            "model": "CBR600RR",
            "reason": "High-output 599 cc four-cylinder; confirm ABS/year.",
        }
    ],
    "queries": ["Honda CBR600RR ABS used NZ"],
    "cautions": ["No blanket displacement cutoff."],
}


def listing(title="2020 Kawasaki Ninja 650", **kwargs):
    return Listing(
        source="trademe",
        listing_id="1",
        canonical_url="https://www.trademe.co.nz/listing/1",
        title=title,
        model_year=2020,
        engine_cc=649,
        asking_price_nzd=10000,
        price_type="ASKING",
        odometer_km=10000,
        **kwargs,
    )


def plan(search):
    return {
        **validate_plan(RAW, search),
        "status": "ready",
        "fingerprint": policy_fingerprint(search),
    }


def test_screening_prevents_detail_research_but_is_not_a_verified_fact(broad_config):
    broad_config["search"]["_operational_plan"] = plan(broad_config["search"])
    item = classify(listing(), broad_config)
    assert item.classification == "REJECTED"
    assert item.evidence["operational_screen"]["verified"] is False
    assert "power_hp" not in item.evidence["suitability"]["facts"]
    assert any("LLM estimate" in reason for reason in item.rejection_reasons)


@pytest.mark.parametrize(
    "title",
    [
        "2020 Honda CBR600RR",
        "2020 Kawasaki Ninja ZX-6R",
        "2020 Kawasaki Ninja 6500",
        "2020 Kawasaki Ninja 650RR",
        "2020 Yamaha Ninja 650",
        "2020 Unknown maker 400 four-cylinder",
    ],
)
def test_unlisted_models_suffixes_and_sub650_sports_bikes_survive(broad_config, title):
    broad_config["search"]["_operational_plan"] = plan(broad_config["search"])
    item = listing(title)
    item.engine_cc = 599
    assert screen(item, broad_config["search"], {}) is None


def test_explicit_specification_beats_family_estimate(broad_config):
    search = broad_config["search"]
    search["_operational_plan"] = plan(search)
    item = listing(description="Full power non-LAMS 90 hp")
    assert screen(item, search, {"power_hp": {"value": 90}}) is None
    classify(item, broad_config)
    assert item.classification == "REVIEW"
    assert "operational_screen" not in item.evidence


def test_no_heuristic_exclusion_when_year_or_identity_unknown(broad_config):
    search = broad_config["search"]
    search["_operational_plan"] = plan(search)
    item = listing()
    item.model_year = None
    assert screen(item, search, {}) is None
    item = listing("Ninja 650")
    item.make = None
    assert screen(item, search, {}) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"models": ["650"]},
        {"models": ["Ninja.*"]},
        {"models": ["Ninja"]},
        {"power_hp_upper": 85},
        {"power_hp_upper": True},
        {"year_min": True},
        {"confidence": "low"},
        {"action": "run_code"},
        {"make": "Kawasaki; cat token.txt"},
    ],
)
def test_invalid_or_overbroad_rules_are_discarded(broad_config, changes):
    raw = copy.deepcopy(RAW)
    raw["rules"][0].update(changes)
    assert not validate_plan(raw, broad_config["search"])["rules"]


def test_main_requirements_invalidate_plan_but_collector_and_keys_do_not(broad_config):
    original = policy_fingerprint(broad_config["search"])
    broad_config["search"]["sources"]["trademe"]["max_pages"] = 20
    broad_config["search"]["_operational_plan"] = {"something": "ignored"}
    assert policy_fingerprint(broad_config["search"]) == original
    broad_config["search"]["requirements"]["min_power_hp"] = 90
    assert policy_fingerprint(broad_config["search"]) != original


def test_compile_once_reuse_including_restart_and_regenerate_on_changed_requirements(
    tmp_path, monkeypatch, broad_config
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    broad_config["database"]["path"] = str(tmp_path / "listings.db")
    calls = []

    def response(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(RAW)}}
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(response))
    first = compile_plan(broad_config, client=client)
    assert first["status"] == "ready"
    assert (
        compile_plan(broad_config, client=client)["fingerprint"] == first["fingerprint"]
    )
    assert len(calls) == 1
    assert read_plan(broad_config)["fingerprint"] == first["fingerprint"]
    assert (tmp_path / "operational-plan.json").stat().st_mode & 0o777 == 0o600
    broad_config["search"]["max_price_nzd"] = 12000
    assert read_plan(broad_config) is None
    assert (
        compile_plan(broad_config, client=client)["fingerprint"] != first["fingerprint"]
    )
    assert len(calls) == 2
    client.close()


def test_failed_planning_does_not_exclude_or_cache_bad_rules(
    tmp_path, monkeypatch, broad_config
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    broad_config["database"]["path"] = str(tmp_path / "listings.db")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    )
    result = compile_plan(broad_config, client=client)
    assert result["status"] == "unavailable"
    assert not result["rules"]
    assert not (tmp_path / "operational-plan.json").exists()
    client.close()


def test_stale_plan_never_screens_new_requirements(broad_config):
    search = broad_config["search"]
    search["_operational_plan"] = plan(search)
    search["requirements"]["min_power_hp"] = 60
    assert screen(listing(), search, {}) is None


def test_literal_aliases_allow_normal_punctuation_only():
    assert model_matches(listing("2020 Yamaha MT 07"), "Yamaha", "MT-07")
    assert not model_matches(listing("2020 Yamaha MT 09"), "Yamaha", "MT-07")


def test_family_generation_scope_is_clamped_to_purchase_years(broad_config):
    raw = copy.deepcopy(RAW)
    raw["rules"][0]["year_min"] = 2014
    result = validate_plan(raw, broad_config["search"])
    assert result["rules"][0]["year_min"] == 2017


def test_dashboard_reads_plan_without_cloud_calls(tmp_path, monkeypatch, broad_config):
    from motorcycle_monitor.web import snapshot

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    broad_config["database"]["path"] = str(tmp_path / "listings.db")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": json.dumps(RAW)},
                        }
                    ]
                },
            )
        )
    )
    cached = compile_plan(broad_config, client=client)
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda *args, **kwargs: pytest.fail("Dashboard must not call the cloud"),
    )
    result = snapshot(broad_config)
    assert result["operational_plan"]["fingerprint"] == cached["fingerprint"]
    assert not (tmp_path / "listings.db").exists()
    client.close()
