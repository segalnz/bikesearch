from copy import deepcopy
from pathlib import Path

import pytest

from motorcycle_monitor.config import DEFAULTS, load_config
from motorcycle_monitor.filtering import classify
from motorcycle_monitor.schema import Listing
from motorcycle_monitor.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def config(tmp_path):
    result = deepcopy(DEFAULTS)
    result["database"]["path"] = str(tmp_path / "live.db")
    result["search"]["sources"] = {
        "trademe": {
            "enabled": True,
            "parser": "jsonld",
            "allowed_hosts": ["www.trademe.co.nz"],
            "search_urls": ["https://www.trademe.co.nz/search"],
        }
    }
    return result


@pytest.fixture
def bike(config):
    def factory(**changes):
        values = dict(
            source="trademe",
            listing_id="123",
            canonical_url="https://www.trademe.co.nz/listing/123",
            title="2021 Kawasaki Ninja 650",
            description="Full power, not LAMS.",
            model_year=2021,
            asking_price_nzd=12000,
            price_type="ASKING",
            odometer_km=5000,
            seller_name="Example seller",
            source_urls=["https://www.trademe.co.nz/listing/123"],
        )
        values.update(changes)
        if "canonical_url" not in changes:
            host = (
                "www.trademe.co.nz"
                if values["source"] == "trademe"
                else "tssmotorcycles.co.nz"
            )
            values["canonical_url"] = f"https://{host}/listing/{values['listing_id']}"
        if "source_urls" not in changes:
            values["source_urls"] = [values["canonical_url"]]
        return classify(Listing(**values), config)

    return factory


@pytest.fixture
def store(tmp_path):
    result = Store(str(tmp_path / "test.db"))
    yield result
    result.close()


@pytest.fixture
def broad_config():
    config = load_config(
        Path(__file__).resolve().parents[1] / "config.bike-search.yaml"
    )
    config["search"]["allowed_locations"] = []
    config["search"]["coverage"] = "nationwide"
    return config
