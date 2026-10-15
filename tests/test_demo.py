from demo import build_demo

from motorcycle_monitor.web import snapshot


def test_demo_is_offline_isolated_and_fictional(tmp_path):
    config = build_demo(tmp_path)
    assert not config["llm"]["enabled"] and not config["mqtt"]["enabled"]
    result = snapshot(config)
    assert result["demo"] is True
    assert len(result["listings"]) == 4
    assert sum(item["classification"] == "ACCEPTED" for item in result["listings"]) == 2
    assert all(
        item["canonical_url"].startswith("https://example.com/")
        for item in result["listings"]
    )
