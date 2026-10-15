import pytest

from motorcycle_monitor.config import load_config
from motorcycle_monitor.filtering import classify, current_criteria
from motorcycle_monitor.schema import Listing


@pytest.fixture
def regional():
    return load_config("config.wellington-ninja.yaml")


def bike(location, **changes):
    values = dict(
        source="trademe",
        listing_id="123",
        canonical_url="https://www.trademe.co.nz/listing/123",
        title="2016 Kawasaki Ninja 650",
        description="Full power, not LAMS",
        model_year=2016,
        odometer_km=9000,
        asking_price_nzd=17000,
        price_type="ASKING",
        location=location,
    )
    values.update(changes)
    return Listing(**values)


@pytest.mark.parametrize(
    "location",
    [
        "Wellington",
        "Lower Hutt, Wellington",
        "Upper Hutt, Wellington",
        "Palmerston North, Manawatu",
        "Terrace End, Palmerston North",
        "Masterton, Wellington",
        "Carterton, Wairarapa",
        "Levin, Manawatu",
        "Waikanae, Wellington",
    ],
)
def test_requested_locations_and_no_price_year_cap(regional, location):
    assert classify(bike(location), regional).classification == "ACCEPTED"


@pytest.mark.parametrize(
    "location",
    ["Auckland, Auckland", "Dunedin, Otago", "Bulls", "Whanganui", "Eketahuna"],
)
def test_outside_area_rejected(regional, location):
    assert classify(bike(location), regional).classification == "REJECTED"


@pytest.mark.parametrize(
    "location",
    [None, "Manawatu", "Wairarapa", "Wellington Region", "Unknown village, Wellington"],
)
def test_uncertain_location_is_review(regional, location):
    assert classify(bike(location), regional).classification == "REVIEW"


def test_under_10000_is_strict(regional):
    assert (
        classify(bike("Wellington", odometer_km=9999), regional).classification
        == "ACCEPTED"
    )
    assert (
        classify(bike("Wellington", odometer_km=10000), regional).classification
        == "REJECTED"
    )
    assert (
        classify(bike("Wellington", description="LAMS"), regional).classification
        == "REJECTED"
    )
    assert (
        classify(
            bike("Wellington", description="Nice motorcycle"), regional
        ).classification
        == "REVIEW"
    )


def test_saved_results_use_changed_criteria(regional):
    data = bike("Dunedin, Otago").to_dict()
    data["classification"] = "ACCEPTED"
    assert current_criteria(data, regional)["classification"] == "REJECTED"
    data = bike("Wellington", title="2025 Suzuki GSX-8R").to_dict()
    assert current_criteria(data, regional)["classification"] == "REJECTED"


def test_regional_validate_does_not_write_deployment_logs(capsys):
    from motorcycle_monitor.cli import main

    assert main(["--config", "config.wellington-ninja.yaml", "validate-config"]) == 0
    assert '"valid": true' in capsys.readouterr().out
