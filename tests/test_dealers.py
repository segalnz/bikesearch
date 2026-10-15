import json
from pathlib import Path

import pytest

from motorcycle_monitor.config import load_config
from motorcycle_monitor.dealers import collect_tss, tss_settings
from motorcycle_monitor.parsers import ParseError

F = Path(__file__).parent / "fixtures"


def test_public_tss_metadata_and_pagination():
    settings = tss_settings((F / "tss-filter-settings.html").read_text())
    assert settings["props"]["epro-loop-builder"]["my-loop7"]["found_posts"] == 29
    result = json.loads((F / "tss-page2.json").read_text())
    assert result["pagination"]["page"] == 2
    assert result["pagination"]["found_posts"] == 11


def test_complete_tss_collection_and_page_guard():
    c = load_config("config.example.yaml")
    o = c["search"]["sources"]["dealer_tss"].copy()
    o["search_urls"] = [o["search_urls"][0]]
    card = (F / "tss-0.html").read_text()

    class FakeFetcher:
        def get(self, url, hosts, *, data=None):
            if data is None:
                return (F / "tss-filter-settings.html").read_text()
            if data["query[_tax_query_vehicle_make]"] == "63":
                return json.dumps(
                    {
                        "pagination": {"found_posts": 0, "max_num_pages": 0, "page": 1},
                        "content": "",
                    }
                )
            page = int(data.get("paged", 1))
            content = card if page == 1 else card.replace("5991876683", "another")
            return json.dumps(
                {
                    "pagination": {"found_posts": 2, "max_num_pages": 2, "page": page},
                    "content": content,
                }
            )

    assert len(collect_tss("dealer_tss", o, FakeFetcher(), c)) == 2

    class Broken(FakeFetcher):
        def get(self, url, hosts, *, data=None):
            if data and data.get("paged") == "2":
                return json.dumps(
                    {
                        "pagination": {"found_posts": 2, "max_num_pages": 2, "page": 1},
                        "content": card,
                    }
                )
            return super().get(url, hosts, data=data)

    with pytest.raises(ParseError, match="schema/page changed"):
        collect_tss("dealer_tss", o, Broken(), c)
