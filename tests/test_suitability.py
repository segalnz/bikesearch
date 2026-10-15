import copy

import pytest

from motorcycle_monitor.filtering import classify, priority
from motorcycle_monitor.schema import Listing
from motorcycle_monitor.suitability import advert_facts


def machine(**changes):
    data = dict(
        source="trademe",
        listing_id="1",
        canonical_url="https://www.trademe.co.nz/a/1",
        title="2020 Example road bike",
        description="Non-LAMS full power. Parallel twin. ABS. Wet weight 209 kg. Seat height 810 mm. 85 hp. Factory screen. English workshop manual included. DIY servicing.",
        model_year=2020,
        asking_price_nzd=12500,
        price_type="ASKING",
        odometer_km=14999,
        location="Lower Hutt, Wellington",
    )
    data.update(changes)
    return Listing(**data)


@pytest.mark.parametrize(
    "changes,classification",
    [
        ({}, "ACCEPTED"),
        ({"asking_price_nzd": 12501}, "REJECTED"),
        ({"model_year": 2016}, "REJECTED"),
        ({"model_year": 2017}, "ACCEPTED"),
        ({"odometer_km": 25000}, "ACCEPTED"),
        ({"odometer_km": 25001}, "REJECTED"),
        ({"location": "Dunedin"}, "ACCEPTED"),
        ({"price_type": "CURRENT_BID"}, "REVIEW"),
        ({"description": "Full power parallel twin ABS; dry weight 190 kg"}, "REVIEW"),
        ({"description": "LAMS, converted to full power"}, "REJECTED"),
        ({"description": "Full power LAMS"}, "REJECTED"),
        ({"description": "Non-LAMS, no ABS"}, "REJECTED"),
        ({"description": "Full power single-cylinder"}, "REJECTED"),
    ],
)
def test_broad_requirements(broad_config, changes, classification):
    assert classify(machine(**changes), broad_config).classification == classification


@pytest.mark.parametrize(
    "weight,status",
    [
        (209.9, "preferred"),
        (210, "acceptable"),
        (215, "acceptable"),
        (225, "acceptable"),
        (225.1, "acceptable"),
    ],
)
def test_weight_preference_is_strictly_under_210(broad_config, weight, status):
    item = machine()
    item.description = item.description.replace("209 kg", f"{weight} kg")
    classify(item, broad_config)
    checks = item.evidence["suitability"]["preferences"]
    assert next(x for x in checks if "Wet weight" in x["label"])["status"] == status
    assert item.classification == ("REJECTED" if weight > 225 else "ACCEPTED")


def test_seat_and_power_preferences_do_not_exclude(broad_config):
    item = machine(model_year=2017, odometer_km=25000)
    item.description = item.description.replace("810 mm", "825 mm").replace(
        "85 hp", "70 hp"
    )
    assert classify(item, broad_config).classification == "ACCEPTED"
    item.description = item.description.replace("825 mm", "826 mm")
    assert classify(item, broad_config).classification == "REJECTED"


def test_preferences_rank_before_price_only_in_broad_search(broad_config):
    preferred = classify(machine(), broad_config).to_dict()
    older = classify(
        machine(model_year=2017, asking_price_nzd=10000), broad_config
    ).to_dict()
    assert priority(preferred, broad_config) < priority(older, broad_config)


def test_dry_and_conflicting_weight_are_unknown():
    assert "wet_weight_kg" not in advert_facts("dry weight 190 kg")
    assert "wet_weight_kg" not in advert_facts("wet weight 209 kg; wet weight 220 kg")


def test_ai_claims_never_satisfy_requirements(broad_config):
    item = machine(description="A nice bike")
    item.evidence["ai_review"] = {"verified": True, "abs": True, "wet_weight_kg": 190}
    assert classify(item, broad_config).classification == "REVIEW"


def test_broad_deployment_replaces_narrow_sources_preserves_data(broad_config):
    from deploy_common import deployment_config

    old = copy.deepcopy(broad_config)
    old["search"]["sources"] = {"trademe": {"search_urls": ["old Ninja URL"]}}
    old["database"]["path"] = "/var/lib/existing.db"
    old["mqtt"]["host"] = "existing-broker"
    updated = deployment_config(old, broad_config, "new")
    assert updated["database"]["path"] == "/var/lib/existing.db"
    assert updated["mqtt"]["host"] == "existing-broker"
    assert updated["search"]["sources"] == broad_config["search"]["sources"]
