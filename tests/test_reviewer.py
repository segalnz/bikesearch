import json

import httpx
import pytest

from motorcycle_monitor.reviewer import Reviewer, validate_review
from motorcycle_monitor.schema import Listing


def test_quote_fabrication_and_wrong_types_rejected():
    with pytest.raises(ValueError):
        validate_review(
            {
                "summary": "test",
                "checks": [
                    {"criterion": "ABS", "assessment": "yes", "quotation": "made up"}
                ],
            },
            "ABS",
        )
    with pytest.raises(ValueError):
        validate_review({"summary": 42, "checks": []}, "ABS")


def test_api_review_cached_bounded_and_advisory(tmp_path):
    token = tmp_path / "token"
    token.write_text("secret-test-key")
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Check variant",
                                    "checks": [
                                        {
                                            "criterion": "ABS",
                                            "assessment": "Advert claim",
                                            "quotation": "ABS",
                                        }
                                    ],
                                }
                            )
                        },
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(response))
    config = {
        "model": "deepseek-flash",
        "max_calls_per_scan": 1,
        "api_key_file": str(token),
    }
    reviewer = Reviewer(config, tmp_path / "cache", client)
    listing = Listing("trademe", "1", "https://www.trademe.co.nz/a/1", "Bike ABS")
    reviewer.review(listing, {})
    assert listing.evidence["ai_review"]["verified"] is False
    assert "Authorization" in requests[0].headers
    again = Reviewer(config, tmp_path / "cache", client)
    again.review(listing, {})
    assert len(requests) == 1
    again.review(listing, {"max_price_nzd": 14000})
    assert len(requests) == 2
    assert json.loads(requests[-1].content)["messages"][1]["content"].find("14000") >= 0
    listing.title = "Different bike"
    reviewer.review(listing, {})
    assert listing.evidence["ai_review"]["status"] == "pending"


def test_failed_api_does_not_leak_response_or_key(tmp_path, caplog):
    token = tmp_path / "token"
    token.write_text("secret-test-key")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, text="secret-test-key")
        )
    )
    reviewer = Reviewer(
        {
            "model": "deepseek-flash",
            "max_calls_per_scan": 1,
            "api_key_file": str(token),
        },
        None,
        client,
    )
    listing = Listing("trademe", "1", "https://www.trademe.co.nz/a/1", "Bike ABS")
    reviewer.review(listing, {})
    assert listing.evidence["ai_review"]["status"] == "unavailable"
    assert "secret-test-key" not in caplog.text
