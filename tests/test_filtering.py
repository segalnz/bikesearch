import pytest


@pytest.mark.parametrize(
    "description,expected",
    [
        ("Full-power version", "ACCEPTED"),
        ("LAMS learner approved", "REJECTED"),
        ("A nice bike", "REVIEW"),
        ("NOT LAMS", "ACCEPTED"),
        ("Unrestricted, LAMS learner-approved", "REVIEW"),
        ("Not full power", "REVIEW"),
        ("Not unrestricted", "REVIEW"),
        ("Was previously LAMS; derestricted", "REVIEW"),
    ],
)
def test_power(bike, description, expected):
    assert bike(description=description).classification == expected


@pytest.mark.parametrize(
    "title,year,expected",
    [
        ("2024 Suzuki GSX-8R", 2024, "ACCEPTED"),
        ("2024 Suzuki GSX 8R", 2024, "ACCEPTED"),
        ("2024 Suzuki GSX-8S", 2024, "REJECTED"),
        ("2021 Kawasaki Z650", 2021, "REJECTED"),
        ("2021 Kawasaki ZX-6R", 2021, "REJECTED"),
        ("2021 Kawasaki Ninja 400", 2021, "REJECTED"),
        ("2021 Kawasaki Ninja 500", 2021, "REJECTED"),
        ("2021 Kawasaki EX650", 2021, "ACCEPTED"),
    ],
)
def test_models(bike, title, year, expected):
    assert bike(title=title, model_year=year).classification == expected


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"asking_price_nzd": 12501}, "REJECTED"),
        ({"odometer_km": 10001}, "REJECTED"),
        ({"model_year": 2019}, "REJECTED"),
        ({"model_year": None}, "REVIEW"),
        ({"odometer_km": None}, "REVIEW"),
        ({"asking_price_nzd": None}, "REVIEW"),
        ({"price_type": "CURRENT_BID", "asking_price_nzd": 1000}, "REVIEW"),
        ({"price_type": "POA"}, "REVIEW"),
        ({"location": "Invercargill"}, "ACCEPTED"),
        ({"title": "Ninja 650 LAMS", "description": "Full power"}, "REVIEW"),
        ({"engine_cc": 650}, "ACCEPTED"),
        ({"engine_cc": 400}, "REJECTED"),
    ],
)
def test_eligibility(bike, changes, expected):
    assert bike(**changes).classification == expected


def test_plausible_missing_model_is_reviewed(bike):
    assert bike(title="2021 Kawasaki Ninja", engine_cc=650).classification == "REVIEW"
    assert (
        bike(title="2021 Kawasaki Ninja 400", engine_cc=650).classification
        == "REJECTED"
    )


def test_financial_priority_before_convenience(bike, config):
    from motorcycle_monitor.filtering import priority

    local = bike(
        asking_price_nzd=12000, location="Lower Hutt", preferred_dealer=True
    ).to_dict()
    nationwide = bike(asking_price_nzd=10000, location="Dunedin").to_dict()
    assert priority(nationwide, config) < priority(local, config)
    local["asking_price_nzd"] = 10000
    assert priority(local, config) < priority(nationwide, config)


def test_conflicting_gsx_displacement_requires_review(bike):
    listing = bike(title="2024 Suzuki GSX-8R", model_year=2024, engine_cc=799)
    assert listing.classification == "REVIEW"
