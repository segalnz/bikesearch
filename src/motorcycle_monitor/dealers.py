"""TSS public filter adapter, verified from normal UI requests and public JS."""

import json

from bs4 import BeautifulSoup

from .normalization import safe_url
from .parsers import ParseError, parse


def form_fields(value: object, prefix: str) -> dict[str, str]:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            result.update(form_fields(item, f"{prefix}[{key}]"))
        return result
    if isinstance(value, list):
        result = {}
        for index, item in enumerate(value):
            result.update(form_fields(item, f"{prefix}[{index}]"))
        return result
    return {prefix: str(value).lower() if isinstance(value, bool) else str(value)}


def tss_settings(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.select("script"):
        text = script.get_text()
        if "var JetSmartFilterSettings =" in text:
            try:
                return json.loads(text[text.index("{") : text.rfind("}") + 1])
            except (json.JSONDecodeError, ValueError) as error:
                raise ParseError("TSS public filter configuration changed") from error
    raise ParseError(
        "TSS public filter metadata missing; cannot verify complete inventory"
    )


def collect_tss(source: str, options: dict, fetcher, config: dict) -> list:
    result = {}
    for url in options["search_urls"]:
        html = fetcher.get(url, options["allowed_hosts"])
        settings = tss_settings(html)
        endpoint = safe_url(settings["ajaxurl"], options["allowed_hosts"])
        providers = settings.get("queries", {}).get("epro-loop-builder", {})
        if len(providers) != 1:
            raise ParseError("TSS public query identity ambiguous")
        query_id = next(iter(providers))
        provider = "epro-loop-builder"
        soup = BeautifulSoup(html, "html.parser")
        select = soup.select_one('select[name="vehicle_make"]')
        if not select:
            raise ParseError("TSS public make selector changed")
        values = {
            node.get_text(" ", strip=True).casefold(): node.get("value")
            for node in select.select("option")
        }
        makes = sorted({rule["make"] for rule in config["search"]["models"]})
        if config["search"].get("mode") == "all_models":
            makes = [
                name
                for name, value in values.items()
                if value and name not in {"all", "all makes", "select make"}
            ]
        for make in makes:
            value = values.get(make.casefold())
            if not value:
                raise ParseError(f"TSS make option missing: {make}")
            body = {
                "action": "jet_smart_filters",
                "provider": provider + "/" + query_id,
                "query[_tax_query_vehicle_make]": value,
            }
            for category, prefix in [
                ("queries", "defaults"),
                ("settings", "settings"),
                ("props", "props"),
            ]:
                body.update(form_fields(settings[category][provider][query_id], prefix))
            page = 1
            seen_ids = set()
            expected = None
            while True:
                # `paged` is the actual parameter in TSS's published public.js.
                page_body = {**body, **({"paged": str(page)} if page > 1 else {})}
                payload = json.loads(
                    fetcher.get(endpoint, options["allowed_hosts"], data=page_body)
                )
                pagination = payload.get("pagination", {})
                total = pagination.get("found_posts")
                max_pages = pagination.get("max_num_pages")
                if (
                    type(total) is not int
                    or type(max_pages) is not int
                    or pagination.get("page") != page
                ):
                    raise ParseError("TSS public pagination schema/page changed")
                if expected is not None and expected != total:
                    raise ParseError(
                        "TSS inventory changed during pagination; retry a later scan"
                    )
                expected = total
                content = payload.get("content")
                if not isinstance(content, str):
                    raise ParseError("TSS public filter content missing")
                parsed = parse(content, url, source, options) if total else []
                for listing in parsed:
                    if listing.listing_id in seen_ids:
                        raise ParseError(
                            "TSS repeated a page; refusing incomplete collection"
                        )
                    seen_ids.add(listing.listing_id)
                    listing.evidence["fetch"].update(
                        search_url=url,
                        adapter="tss_public_filter",
                        make=make,
                        page=page,
                    )
                    result[(listing.source, listing.listing_id)] = listing
                if page >= max_pages:
                    if len(seen_ids) != total:
                        raise ParseError(
                            f"TSS reported {total} bikes but collected {len(seen_ids)}"
                        )
                    break
                page += 1
    return list(result.values())
