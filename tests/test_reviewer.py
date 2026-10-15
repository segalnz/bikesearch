import json

import httpx
import pytest

from motorcycle_monitor.reviewer import Reviewer, validate_review
from motorcycle_monitor.schema import Listing


def test_unsupported_quotation_is_removed_and_wrong_shape_rejected():
    result = validate_review(
        {
            "summary": "test",
            "checks": [
                {
                    "criterion": "ABS",
                    "assessment": "AI suggestion",
                    "quotation": "made up",
                }
            ],
        },
        "ABS",
    )
    assert result["checks"][0]["quotation"] == ""
    assert result["checks"][0]["quotation_verified"] is False
    assert result["checks"][0]["quotation_discarded"] is True
    assert "made up" not in json.dumps(result)
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


def test_invalid_response_does_not_disable_other_candidate_reviews(tmp_path):
    path = tmp_path / "token"
    path.write_text("synthetic-key")
    responses = iter(
        [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"summary": "Check variant", "checks": []}
                            )
                        },
                    }
                ]
            },
        ]
    )
    reviewer = Reviewer(
        {"model": "deepseek-flash", "max_calls_per_scan": 2, "api_key_file": str(path)},
        None,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=next(responses))
            )
        ),
    )
    first = Listing("test", "1", "https://example.com/1", "First bike")
    second = Listing("test", "2", "https://example.com/2", "Second bike")
    reviewer.review(first, {})
    reviewer.review(second, {})
    assert first.evidence["ai_review"]["status"] == "unavailable"
    assert second.evidence["ai_review"]["status"] == "advisory"
    assert reviewer.calls == 2
