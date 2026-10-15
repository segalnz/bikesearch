# Current search requirements

Edit `config.bike-search.yaml`, then redeploy from the desktop with
`./scripts/redeploy.sh`. To switch from the former Ninja-only preset, use
`./scripts/redeploy.sh --preset config.bike-search.yaml` once.

| Criterion | Required / limit | Preference |
| --- | --- | --- |
| Price | Fixed asking/buy-now up to NZ$12,500 inclusive | — |
| Model year | 2017 onward | 2020 onward |
| Mileage | Up to 25,000 km inclusive | Strictly under 15,000 km |
| Engine | Two, three or four cylinders | — |
| Power | Confirmed non-LAMS; exclude converted/conflicting LAMS adverts | At least 80 hp |
| Wet weight | Up to 225 kg | **Strictly under 210 kg** |
| Seat height | Up to 825 mm | Up to 810 mm |
| ABS | Mandatory | — |
| Weather protection | — | Factory screen or half/full fairing |
| Market | — | Model sold in USA |
| Servicing | DIY suitability and obtainable English workshop documentation | — |
| Location | New Zealand | Wellington / Lower North Island |

The approximate 225 kg maximum is implemented as an inclusive numerical ceiling;
change `requirements.max_wet_weight_kg` to adjust that tolerance. Dry weights
never substitute for wet weights. Preferences order candidates, with financial
comparison next. Missing preferences do not exclude bikes. Missing mandatory
facts produce **Needs review**, with a reason for each outstanding check.

Current automated factual extraction uses explicit advert wording. Model names
alone do not establish ABS, wet weight, seat height, unrestricted power or workshop
support. Seller claims require confirmation of the exact year/NZ variant. This
means many plausible bikes initially need review; the application does not invent
specifications to produce more confirmed matches. US-market status remains
unconfirmed unless researched; AI discussion is separate from verified evidence.

## Public search coverage

Trade Me price/year controls and `page=` pagination were checked against the
public site. Price/year acquisition parameters are regenerated from the policy on each scan,
so editing the criteria cannot leave an old URL ceiling in effect. Odometer is
independently filtered locally; its URL parameter is not
relied on for eligibility. The broad search is deliberately model-independent.
Six search pages and up to twelve promising detail adverts are inspected per
scan. The first page is revisited; later pages rotate using a local cursor in the
HTTP cache directory. Set `max_pages` / `max_details` under the source to adjust.
Local and explicitly unrestricted candidates get detail-reading priority.

A broad nationwide search returns thousands of bikes, including singles and
LAMS adverts. Coverage is **partial**, clearly noted in Collection health.
Partial Trade Me scans never mark unseen listings unavailable. Previously saved
bikes remain in history, evaluated against the new requirements; their last-seen
time shows how recent the evidence is. Complete dealer scans retain normal
missing-listing tracking. An exhausted HTTP budget or changed page structure is
an explicit source error. The configured request budget and systemd timeout
still bound work; increasing coverage also increases scan duration.

## DeepSeek review

The monitor calls DeepSeek directly using `httpx`; no OpenClaw installation or
additional agent service is required. The available model was verified through
`GET https://api.deepseek.com/models`; the preset uses `deepseek-flash` in
non-thinking JSON-output mode. Documentation:
[JSON output](https://api-docs.deepseek.com/guides/json_mode/) and
[thinking control](https://api-docs.deepseek.com/guides/thinking_mode/).

Eligible/uncertain adverts receive a bounded, cached research assessment about
ABS, cylinders, weight, seat height, non-LAMS variants, US sale, workshop manuals
and DIY/diagnostic caveats. The dashboard exposes this under **DeepSeek research
guidance**. These are advisory checks, not independent web verification: this API
integration has no browsing tool. Memory-based manufacturer specifications or
manual availability never automatically satisfy a mandatory requirement. Quoted
advert passages must exactly match the supplied advert; unsupported quotations
are removed from the advisory, and malformed candidate responses are isolated. AI cannot override deterministic exclusions.

At most 16 calls and 180 cumulative API seconds are allowed per scan. Unchanged advert/criteria/model combinations
reuse `/var/lib/motorcycle-monitor/ai-cache`; changed adverts or preferences get
new reviews. Credential/API connection errors stop further review calls for that scan; a
malformed candidate response affects only that candidate. Both leave collection
running and keep unknown requirements marked for review. Requests use a 60-second
timeout and bounded input/output. Dry-runs can call the paid API but do not write
its disk cache. Set `llm.enabled: false` to disable cloud calls.

The desktop token files are ignored by Git. They may contain labelled keys; the
deployer extracts only the DeepSeek key and never transfers the GitHub key. It never
enters the application archive. Broad-preset redeployment transfers it separately
over SSH and installs `/etc/motorcycle-monitor/deepseek.token` as root, group
`motorcycle-monitor`, mode 0640. No credentials enter prompts, logs or dashboard
responses. Only public advert text and requirements are submitted to DeepSeek.
Alternatively set `DEEPSEEK_API_KEY` in the service environment. Keep Python and
all package installation inside the LXC virtualenv as before.

## Wider-web coverage

The broad preset enables ten independent source adapters: Trade Me, TSS,
Cyclespot Wellington, Courtesy, Maidstone Yamaha, Langlands Honda, THS Moto,
Colemans, Cooks Honda and Turners. These represent eight dealer sites and two
marketplaces, not ten copies of the same Trade Me search. They include the
preferred Wellington/Manawatu/Wairarapa area and nationwide stock. Source links
are retained, and ambiguous cross-site duplicates are not silently merged.
Independent websites are always marked partial unless a complete adapter has
proved otherwise. Public-page parser failures are visible in Collection health.

The disabled `web_search` source adds general indexed discovery through Brave
Search or Tavily when a separate search-provider key is available. A DeepSeek key
is for model inference and does not grant either service's search API access.
Set `provider`, enable the source and install its key in
`/etc/motorcycle-monitor/search.token` (root/service group, mode 0640), or set
`BRAVE_SEARCH_API_KEY` / `TAVILY_API_KEY` in the service environment. At most four
queries and twelve result documents are followed per scan. Queries cover local
and national used motorcycles without fixing the search to specific models.
Newly discovered hosts must be public NZ hosts, with safe schemes/ports and DNS
checks that reject private/LAN addresses. An API result is only a lead until its
actual source page yields recognized inventory or listing evidence.

Search-provider implementations follow the official
[Brave Web Search API](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started)
and [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search).
Their contracts are tested with mock responses; live indexed API execution needs
that provider's own key and has not been verified with the DeepSeek key.

Some automated public search requests from the development environment received
CAPTCHA/rate-limit pages. This is not a claim that the owner's ordinary browser
or local network blocks web search. The monitor distinguishes an app shell that
needs standard browser rendering from an explicit challenge. Challenged sources
are recorded as errors, suppressed for that scan, and other independent sites
continue; the application never reports those failures as zero qualifying bikes.
