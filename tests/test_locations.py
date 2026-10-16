from pathlib import Path

import pytest
from test_suitability import machine

from motorcycle_monitor.config import load_config
from motorcycle_monitor.filtering import classify
from motorcycle_monitor.locations import area_status
from motorcycle_monitor.search_plan import policy_fingerprint
from motorcycle_monitor.suitability import is_candidate


@pytest.fixture
def regional_config():
    return load_config(Path(__file__).resolve().parents[1] / "config.bike-search.yaml")


@pytest.mark.parametrize(
    "location,status",
    [
        ("Lower Hutt, Wellington", "inside"),
        ("Trentham, Wellington", "inside"),
        ("Palmerston North, Manawatu", "inside"),
        ("Masterton, Wairarapa", "inside"),
        ("Ōtaki, Wellington", "inside"),
        ("Wanaka, Otago Region", "outside"),
        ("East Tamaki, Auckland", "outside"),
        ("Takapuna, North Shore", "outside"),
        ("New Plymouth", "outside"),
        ("Napier", "outside"),
        ("Whanganui", "outside"),
        ("", "unknown"),
        ("Wairarapa", "unknown"),
        ("Manawatu", "unknown"),
        ("Unknown village, Wellington", "unknown"),
    ],
)
def test_hard_corridor(regional_config, location, status):
    assert (
        area_status(location, regional_config["search"]["allowed_locations"]) == status
    )
    item = classify(machine(location=location), regional_config)
    assert is_candidate(item) == (status == "inside")
    assert (
        item.classification
        == {"inside": "ACCEPTED", "outside": "REJECTED", "unknown": "REVIEW"}[status]
    )


def test_delivery_prose_cannot_admit_outside_listing(regional_config):
    item = machine(location="Auckland")
    item.description += " Free delivery to Wellington, Palmerston North and Masterton."
    assert classify(item, regional_config).classification == "REJECTED"


def test_town_changes_invalidate_saved_operational_plan(regional_config):
    before = policy_fingerprint(regional_config["search"])
    regional_config["search"]["allowed_locations"].append("Example town")
    assert policy_fingerprint(regional_config["search"]) != before
