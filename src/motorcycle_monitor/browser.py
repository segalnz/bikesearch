"""Optional standard Chromium rendering for publicly accessible app pages."""

from urllib.parse import urlsplit

from .normalization import safe_url


def render(url: str, hosts: list[str], config: dict) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Install the browser extra in your virtualenv: pip install '.[browser]'"
        ) from error
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=config.get("browser_executable") or None
        )
        try:
            context = browser.new_context(service_workers="block")
            page = context.new_page()
            problems = []
            resource_count = 0

            def route_request(route):
                nonlocal resource_count
                request = route.request
                hostname = urlsplit(request.url).hostname or ""
                if problems:
                    route.abort()
                    return
                # No downloads of photos, ads, media or external analytics.
                if request.resource_type in {
                    "image",
                    "media",
                    "font",
                    "stylesheet",
                } or not (
                    hostname == "trademe.co.nz" or hostname.endswith(".trademe.co.nz")
                ):
                    route.abort()
                    return
                resource_count += 1
                if resource_count > config.get("browser_resource_budget", 400):
                    if "Browser resource budget exhausted" not in problems:
                        problems.append("Browser resource budget exhausted")
                    route.abort()
                    return
                if request.is_navigation_request() and request.frame == page.main_frame:
                    try:
                        safe_url(request.url, hosts)
                    except ValueError as error:
                        problems.append(str(error))
                        route.abort()
                        return
                route.continue_()

            def check_response(response):
                if (
                    response.status in {403, 429}
                    and response.request.resource_type in {"document", "xhr", "fetch"}
                    and "/csp-report-uri" not in response.url
                ):
                    problems.append(
                        f"HTTP {response.status} during public render: {response.url}; stop source"
                    )

            page.route("**/*", route_request)
            page.on("response", check_response)
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=int(config["request_timeout_seconds"] * 1000),
            )
            if not response or response.status != 200:
                raise RuntimeError(
                    f"Browser HTTP {response.status if response else 'no response'}"
                )
            try:
                page.wait_for_function(
                    r"""() => {
                    const count = document.querySelector('tm-search-header-result-count h3');
                    if (count) {
                        const match = count.textContent.match(/Showing\s+([\d,]+)\s+results/);
                        if (!match) return false;
                        const total = Number(match[1].replaceAll(',', ''));
                        return total === 0 || document.querySelectorAll('a.tm-tiered-search-card__link').length >= Math.min(total, 20);
                    }
                    return !!document.querySelector('h1.tm-motors-listing__title') &&
                           !!document.querySelector('tm-motors-listing-description') &&
                           !!document.querySelector('tm-motors-listing-json-ld script');
                }""",
                    timeout=int(config["request_timeout_seconds"] * 1000),
                )
            except Exception as error:
                if problems:
                    raise RuntimeError("; ".join(problems)) from error
                raise RuntimeError(
                    "Public page did not render recognized listing/search content; check structure or use manual imports"
                ) from error
            if problems:
                raise RuntimeError("; ".join(problems))
            safe_url(page.url, hosts)
            return page.content()
        finally:
            browser.close()
