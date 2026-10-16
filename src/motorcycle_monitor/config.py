from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .normalization import safe_url

DEFAULTS: dict[str, Any] = {
    "search": {
        "max_price_nzd": 12500,
        "max_odometer_km": 10000,
        "preferred_regions": ["Wellington", "Hutt", "Kapiti", "Wairarapa", "Manawatu"],
        "models": [
            {
                "make": "Kawasaki",
                "model": "Ninja 650",
                "min_year": 2020,
                "require_unrestricted": True,
            },
            {
                "make": "Suzuki",
                "model": "GSX-8R",
                "min_year": 2024,
                "require_unrestricted": True,
            },
        ],
        "sources": {},
    },
    "collector": {
        "mode": "http",
        "request_interval_seconds": 10,
        "max_concurrency": 1,
        "request_timeout_seconds": 30,
        "max_requests": 30,
        "max_retries": 2,
        "cache_seconds": 3600,
        "enable_browser_fallback": False,
    },
    "alerts": {
        "price_drop_nzd": 500,
        "price_drop_percent": 5,
        "notify_unknown_power": True,
        "notify_initial_results": False,
    },
    "mqtt": {
        "enabled": False,
        "host": "localhost",
        "port": 1883,
        "topic_prefix": "motorcycles",
        "qos": 1,
    },
    "database": {"path": "./data/listings.db"},
    "logging": {"level": "INFO", "path": None},
    "llm": {"enabled": False},
    "availability": {"missing_scans": 2, "minimum_hours_between_misses": 12},
    "web": {"host": "0.0.0.0", "port": 8765, "refresh_seconds": 60},
}


def merge(base: dict, overrides: dict) -> dict:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: str | Path) -> dict:
    try:
        raw = yaml.safe_load(Path(path).read_text()) or {}
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML configuration: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("Configuration must be a YAML mapping")
    config = merge(deepcopy(DEFAULTS), raw)
    validate(config)
    return config


def validate(config: dict) -> None:
    for section in DEFAULTS:
        if not isinstance(config[section], dict):
            raise ValueError(f"{section} must be a mapping")
    if (
        type(config["availability"]["missing_scans"]) is not int
        or config["availability"]["missing_scans"] < 2
    ):
        raise ValueError("availability.missing_scans must be at least 2")
    if (
        not isinstance(
            config["availability"]["minimum_hours_between_misses"], (int, float)
        )
        or config["availability"]["minimum_hours_between_misses"] <= 0
    ):
        raise ValueError("minimum_hours_between_misses must be positive")
    if not isinstance(config["web"]["host"], str) or not config["web"]["host"]:
        raise ValueError("web.host must be a listen address")
    if (
        type(config["web"]["port"]) is not int
        or not 1 <= config["web"]["port"] <= 65535
    ):
        raise ValueError("web.port must be between 1 and 65535")
    if (
        type(config["web"]["refresh_seconds"]) is not int
        or config["web"]["refresh_seconds"] < 15
    ):
        raise ValueError("web.refresh_seconds must be at least 15")
    price = config["search"]["max_price_nzd"]
    if price is not None and (type(price) is not int or price <= 0):
        raise ValueError(
            "max_price_nzd must be a positive integer or null for no ceiling"
        )
    locations = config["search"].get("allowed_locations", [])
    if not isinstance(locations, list) or not all(
        isinstance(place, str) and place.strip() for place in locations
    ):
        raise ValueError("allowed_locations must be a list of location names")
    for section, keys in {
        "search": ("max_odometer_km",),
        "collector": (
            "request_interval_seconds",
            "request_timeout_seconds",
            "max_requests",
            "cache_seconds",
        ),
        "alerts": ("price_drop_nzd", "price_drop_percent"),
    }.items():
        for key in keys:
            value = config[section][key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value <= 0
            ):
                raise ValueError(f"{section}.{key} must be positive")
    if config["collector"]["request_interval_seconds"] < 10:
        raise ValueError("Minimum request interval is 10 seconds")
    if (
        type(config["collector"].get("browser_resource_budget", 400)) is not int
        or not 1 <= config["collector"].get("browser_resource_budget", 400) <= 2000
    ):
        raise ValueError(
            "browser_resource_budget must be an integer between 1 and 2000"
        )
    if config["collector"]["max_concurrency"] != 1:
        raise ValueError("Only max_concurrency: 1 is supported")
    if config["collector"]["mode"] not in {"http", "auto"}:
        raise ValueError("Only HTTP acquisition is implemented")
    if config["llm"].get("research_enabled", False):
        if not config["llm"]["enabled"]:
            raise ValueError("Model research requires llm.enabled")
        for key, maximum in [
            ("research_calls_per_scan", 100),
            ("research_seconds", 600),
        ]:
            value = config["llm"].get(
                key, 24 if key == "research_calls_per_scan" else 240
            )
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"llm.{key} outside supported budget")
    if config["llm"]["enabled"]:
        seconds = config["llm"].get("max_review_seconds", 180)
        if type(seconds) not in {int, float} or not 1 <= seconds <= 600:
            raise ValueError("llm.max_review_seconds must be between 1 and 600")
        if config["llm"].get("provider") != "deepseek":
            raise ValueError("Only the DeepSeek reviewer is supported")
        if config["llm"].get("model") not in {"deepseek-flash", "deepseek-v4-pro"}:
            raise ValueError("Choose a supported DeepSeek model")
        if (
            type(config["llm"].get("max_calls_per_scan")) is not int
            or not 1 <= config["llm"]["max_calls_per_scan"] <= 100
        ):
            raise ValueError("llm.max_calls_per_scan must be between 1 and 100")
        if (
            not isinstance(config["llm"].get("api_key_file"), str)
            or not config["llm"]["api_key_file"]
        ):
            raise ValueError("llm.api_key_file is required")
    if (
        type(config["collector"]["max_retries"]) is not int
        or not 0 <= config["collector"]["max_retries"] <= 5
    ):
        raise ValueError("max_retries must be an integer between 0 and 5")
    if config["mqtt"]["qos"] != 1 or not 1 <= config["mqtt"]["port"] <= 65535:
        raise ValueError("MQTT requires QoS 1 and a valid port")
    if not config["mqtt"]["topic_prefix"] or any(
        c in config["mqtt"]["topic_prefix"] for c in "#+\0"
    ):
        raise ValueError("Invalid MQTT topic prefix")
    for section, key in [
        ("mqtt", "enabled"),
        ("llm", "enabled"),
        ("alerts", "notify_unknown_power"),
        ("alerts", "notify_initial_results"),
        ("collector", "enable_browser_fallback"),
    ]:
        if type(config[section][key]) is not bool:
            raise ValueError(f"{section}.{key} must be a boolean")
    if not config["database"]["path"]:
        raise ValueError("database.path is required")
    for model in config["search"]["models"]:
        if model["model"] not in {"Ninja 650", "GSX-8R"} or (
            model["min_year"] is not None
            and (type(model["min_year"]) is not int or model["min_year"] < 1900)
        ):
            raise ValueError("Unsupported model or invalid min_year")
        if type(model.get("require_unrestricted", True)) is not bool:
            raise ValueError("require_unrestricted must be boolean")
    for key in ("max_requests", "cache_seconds", "request_timeout_seconds"):
        if type(config["collector"][key]) is not int:
            raise ValueError(f"collector.{key} must be an integer")
    if not isinstance(config["search"]["models"], list) or (
        not config["search"]["models"] and config["search"].get("mode") != "all_models"
    ):
        raise ValueError("search.models must be a nonempty list")
    if config["search"].get("mode", "models") not in {"models", "all_models"}:
        raise ValueError("Invalid search.mode")
    if config["search"].get("mode") == "all_models":
        _validate_broad(config["search"])
    if not isinstance(config["search"]["sources"], dict):
        raise ValueError("search.sources must be a mapping")
    if config["alerts"]["price_drop_percent"] > 100:
        raise ValueError("price_drop_percent must not exceed 100")
    if not isinstance(config["logging"]["level"], str) or config["logging"][
        "level"
    ] not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("Invalid logging.level")
    for key, scenario in config.get("changeover", {}).get("scenarios", {}).items():
        if (
            scenario.get("kind") not in {"trade_in", "private_sale"}
            or type(scenario.get("valuation_id")) is not int
            or scenario["valuation_id"] <= 0
        ):
            raise ValueError(f"Invalid changeover scenario {key}")
        if scenario.get("expenses_nzd") is not None and (
            type(scenario["expenses_nzd"]) is not int or scenario["expenses_nzd"] < 0
        ):
            raise ValueError("Scenario expenses must be a non-negative integer or null")
    for name, source in config["search"]["sources"].items():
        if not isinstance(source, dict):
            raise ValueError(f"{name} must be a source mapping")
        if type(source.get("enabled", False)) is not bool:
            raise ValueError(f"{name}.enabled must be boolean")
        if type(source.get("allow_partial", False)) is not bool:
            raise ValueError(f"{name}.allow_partial must be boolean")
        for key, lower, upper in [("max_pages", 1, 30), ("max_details", 0, 50)]:
            value = source.get(key, lower)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{name}.{key} is outside the supported budget")
        if source.get("parser") == "indexed_search":
            if source.get("provider") not in {"brave", "tavily"}:
                raise ValueError("Indexed search requires Brave or Tavily")
            if (
                not isinstance(source.get("api_key_file"), str)
                or not source["api_key_file"]
            ):
                raise ValueError("Indexed search requires api_key_file")
            if (
                not isinstance(source.get("queries"), list)
                or not source["queries"]
                or not all(isinstance(q, str) and q.strip() for q in source["queries"])
            ):
                raise ValueError("Indexed search needs nonempty queries")
            if not source.get("allow_partial"):
                raise ValueError("Indexed searches must declare partial coverage")
        hosts = source.get("allowed_hosts", [])
        if not isinstance(hosts, list) or not all(
            isinstance(h, str) and h for h in hosts
        ):
            raise ValueError(f"{name}.allowed_hosts must be a list of hostnames")
        if not isinstance(source.get("search_urls", []), list):
            raise ValueError(f"{name}.search_urls must be a list")
        for url in source.get("search_urls", []):
            safe_url(url, hosts)
        if source.get("detail_parser") is not None and source["detail_parser"] not in {
            "jsonld",
            "trademe_detail",
        }:
            raise ValueError(f"Unsupported detail_parser for {name}")
        if source.get("parser", "jsonld") not in {
            "jsonld",
            "website",
            "indexed_search",
            "tss",
            "cyclespot",
            "trademe",
            "trademe_detail",
        }:
            raise ValueError(f"Unsupported parser for {name}")


def _validate_broad(search):
    requirements = search.get("requirements", {})
    preferences = search.get("preferences", {})
    for mapping, keys in [
        (search, ["min_year"]),
        (requirements, ["max_wet_weight_kg", "max_seat_height_mm"]),
        (
            preferences,
            [
                "min_year",
                "odometer_under_km",
                "wet_weight_under_kg",
                "min_power_hp",
                "max_seat_height_mm",
            ],
        ),
    ]:
        for key in keys:
            value = mapping.get(key)
            if type(value) not in {int, float} or value <= 0:
                raise ValueError(f"{key} must be a positive number")
    minimum = requirements.get("min_power_hp")
    if minimum is not None and (
        type(minimum) not in {int, float} or not 0 < minimum < 1000
    ):
        raise ValueError(
            "requirements.min_power_hp must be a positive horsepower limit"
        )
    if search["max_price_nzd"] is None:
        raise ValueError("Broad search needs a price ceiling")
    if requirements.get("cylinders") != [2, 3, 4]:
        raise ValueError("Broad search supports cylinders [2, 3, 4]")
    for key in ["abs", "english_manual", "diy_serviceable"]:
        if type(requirements.get(key)) is not bool:
            raise ValueError(f"requirements.{key} must be boolean")
    for preferred, maximum in [
        ("wet_weight_under_kg", "max_wet_weight_kg"),
        ("max_seat_height_mm", "max_seat_height_mm"),
    ]:
        if preferences[preferred] > requirements[maximum]:
            raise ValueError("Preference exceeds required maximum")
