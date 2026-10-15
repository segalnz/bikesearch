# Trade Me Motorcycle Monitor
## Consolidated software specification — Version 1.1

**Purpose:** Build a small, reliable, self-hosted Python service to monitor public motorcycle listings on Trade Me and selected dealer websites, filter and track suitable motorcycles, and notify the user of new opportunities and meaningful price reductions. Personal purchasing research only; no republishing, automated messaging, bidding, or purchases.

**Target deployment:** Debian/Ubuntu Linux LXC under Proxmox, with SQLite persistence and MQTT notification to existing Node-RED/Home Assistant. No Docker or LLM required for core operation.

## 1. Search requirements

| Model | Model years | Engine/power | Rules |
|---|---|---|---|
| Kawasaki Ninja 650 (EX650) | 2020 onward | Unrestricted/full-power 649 cc twin | Reject confirmed LAMS/restricted bikes; do not confuse with Z650, Ninja 400/500 or ZX-6R |
| Suzuki GSX-8R | 2024 onward | Unrestricted/full-power 776 cc twin | Reject confirmed restricted variants; do not confuse with GSX-8S |

- Maximum advertised asking/buy-now price: **NZ$12,500**.
- Maximum odometer: **10,000 km**.
- Nationwide coverage, prioritising Wellington/Hutt Valley/Kapiti/Wairarapa, then the Lower North Island.
- Include private sellers, dealers, demonstrators and new/used motorcycles.
- Distinguish asking/buy-now prices from auction current bids, reserve uncertainty, and price-on-application. A low current bid is **not** evidence of a qualifying purchase price.
- Treat missing model year, mileage, price, power variant or other material facts as **unknown**, not as qualifying facts; route plausible listings to review.
- Search frequency: **daily**, configurable, initially 08:00 Pacific/Auckland.
- All criteria configurable without code changes.

## 2. Trade-in context and priority dealerships

The buyer currently owns a **2025 Suzuki V-Strom 250SX**, which may be traded against the replacement. A dealer purchase with trade-in can be advantageous even if the advertised motorcycle price is higher than a private sale.

- Prioritise **TSS Motorcycles** (Suzuki, Lower Hutt) and **Cyclespot Wellington** (Kawasaki, Lower Hutt). Confirm dealer names/locations against current websites before implementing identifiers; the user has also referred to 'Cycleworks'.
- Monitor dealer-owned websites as separate collection adapters, alongside their Trade Me advertisements, if publicly accessible and technically feasible.
- Cross-identify identical bikes advertised on multiple sites; avoid duplicate alerts while preserving every source URL.
- Track `seller_type` (dealer/private/unknown), `dealer_name`, `preferred_dealer`, and `trade_in_available` (yes/no/unknown). A dealer listing does not prove that trade-in is offered.
- Store manually entered dealer trade-in quotes and expected private-sale proceeds, with date and provenance; **never invent valuations**.
- Compare **changeover cost** rather than asking price alone when sufficient inputs are available:
  - Dealer: `asking_price + ORC + travel/delivery/other purchase expenses - actual_or_estimated_trade_in_allowance`.
  - Private purchase: `asking_price + travel/delivery/other purchase expenses - actual_or_estimated_net_private_sale_proceeds`.
- Show assumptions and unknowns plainly. Record actual dealer quotes separately from estimates.
- Ranking should give local dealers greater convenience priority, **not** override a poor financial deal or core eligibility criteria.

## 3. Architecture

Implement small, separable, testable modules:

1. `collectors`: per-source acquisition adapters (Trade Me, dealer sites).
2. `parsers`: source HTML/structured-data to common listing schema.
3. `normalization`: currency, dates, mileage, model codes, seller and URL normalization.
4. `filtering`: deterministic eligibility and review rules.
5. `classification`: model and restricted-power classification, optional LLM enhancement.
6. `storage`: SQLite database, migrations, observation history and transactional alert outbox.
7. `notifications`: MQTT event publisher (optional email later).
8. `scheduler`: systemd timer using one-shot CLI execution.
9. `cli`: manual scans, inspections, dry runs and health diagnostics.
10. `model_support`: cached research on servicing, workshop manuals and aftermarket parts.

Avoid a monolithic script or unnecessary agent frameworks.

## 4. Acquisition design

- Use configurable **search URLs** obtained and checked manually, rather than guessing undocumented URL patterns.
- Start with `httpx` and `BeautifulSoup` (or another established HTML parser); use structured data/embedded JSON where present.
- Provide optional Playwright/Chromium adapter **only if necessary** for public, JavaScript-rendered pages. Do not require Chromium if basic HTTP works.
- Broaden search terms to account for spelling/spacing/model code variants; apply exact filtering locally.
- Fetch listing detail pages selectively when search results lack essential fields. Cache requests and avoid unnecessary downloads or image scraping.
- Keep collectors replaceable when page structures change.
- No login automation, credential handling, CAPTCHA solving, proxy rotation, access-control circumvention, identity spoofing, or automated seller contact.
- Use conservative pacing (e.g. default minimum 10 seconds between requests), `max_concurrency: 1`, reasonable timeouts, exponential backoff and a bounded request budget. Stop and report 403/429/blocked access instead of evasion.
- Trade Me's terms may prohibit automated collection. This is a project risk to recognise, not a claim that every collection of public facts is necessarily unlawful. Operators are responsible for lawful use.
- If a site blocks acquisition, fail visibly; offer native saved-search alerts or manual imports as fallback rather than silently skipping it.
- Collect only data necessary for personal purchasing decisions; do not redistribute seller descriptions or photographs.

## 5. Normalized listing schema

Required or nullable fields:

- `source`, `listing_id`, `canonical_url`, `source_urls[]`, `title`, `description` (short relevant text), `make`, `model`, `model_year`, `engine_cc`.
- `asking_price_nzd`, `price_type` (`ASKING`, `BUY_NOW`, `CURRENT_BID`, `POA`, `UNKNOWN`), `orc_nzd` (nullable), `odometer_km`.
- `location`, `seller_name`, `seller_type` (`DEALER`, `PRIVATE`, `UNKNOWN`), `dealer_name`, `preferred_dealer`, `trade_in_available` (`YES`, `NO`, `UNKNOWN`).
- `power_status` (`UNRESTRICTED`, `RESTRICTED`, `UNKNOWN`), `power_evidence`, `classification` (`ACCEPTED`, `REJECTED`, `REVIEW`), `rejection_reasons[]`.
- `listing_status` (`ACTIVE`, `ENDED`, `UNKNOWN`), `first_seen_utc`, `last_seen_utc`, `last_changed_utc`.
- Add evidence/source and timestamp fields for sensitive classifications and dealer information.
- Use explicit null for missing data. Prices in integer NZD, distances in integer km, times in UTC, displayed in Pacific/Auckland.
- Preserve exact original clickable listing URL. Validate URL scheme and hostname before including links in messages.

## 6. Filtering and power verification

- Do deterministic name/model normalization and model-family exclusion before optional natural-language interpretation.
- Example accepted models: full-power Kawasaki Ninja 650/appropriate EX650 variants; Suzuki GSX-8R.
- Example excluded models: Kawasaki Z650, Ninja 400, Ninja 500, ZX-6R; Suzuki GSX-8S.
- Explicit LAMS/learner-approved/restricted-power evidence causes `RESTRICTED` status. Guard against negation ("NOT LAMS") and contradictory seller descriptions.
- **Absence of the word LAMS is not proof of unrestricted power.** Require positive evidence: verified factory variant codes, authoritative model documentation, or explicit supported details in the advert. Conflicting evidence gives `UNKNOWN` pending review.
- Accept only confirmed eligible bikes. Plausible bikes with unknown critical fields go into the review queue and may trigger *clearly labelled* review alerts.
- Reject confirmed price/year/mileage failures. Do not reject solely on location.
- Grade source evidence and preserve concise reasoning so the owner can verify dubious advertisements.

## 7. SQLite persistence

Use migrations, WAL mode and unique constraints. Suggested tables:

- `listings`: normalized current listing; unique `(source, listing_id)`.
- `observations`: time, asking price, mileage, status, fingerprint, fetch provenance.
- `listing_sources`: cross-site URLs and identities (for dealer + Trade Me duplication).
- `notifications`: stable event ID, type, payload, delivery state, attempt counts, last error.
- `collection_runs`: timestamps, adapter, URLs checked, counts by parsed/accepted/review/filtered, HTTP/parser/errors, outcome.
- `trade_in_quotes`: seller, value, basis, quote date, expiry, notes; `private_sale_estimates` similarly.
- `model_support`: persistent model generation, source-backed parts/manual assessment, verification date.

Use transactions and an **outbox pattern**: recording a listing/event must be separate from successful MQTT delivery, allowing reliable retry and crash recovery. Preserve price history and prevent duplicate notifications for unchanged listings. Do not presume a motorcycle has sold because it vanishes from one broken scan. Detect likely relistings but require review before merging uncertain matches.

## 8. Alert logic

Events:

- `NEW_LISTING`: newly found, confirmed qualifying listing.
- `PRICE_DROP`: confirmed listing falls at least **NZ$500 or 5%, whichever is smaller**, measured against the last notified price; configurable.
- `REVIEW_REQUIRED`: otherwise promising listing lacks trustworthy essential evidence (especially full-power confirmation).
- `LISTING_REACTIVATED`: previously ended/unknown listing returns and appears available.
- `SYSTEM_ERROR`: persistent collection/parser/database/publisher errors.

On first successful run, build a baseline and issue **one summary** rather than individual new-listing alerts; offer `--notify-initial` override. No notifications for unchanged listings. Avoid alert flooding on repeated failed scans or retries. A meaningful price reduction must not rely on a changing **current auction bid**.

Each alert must include bike/year, asking/buy-now price, mileage, location, seller/dealer, power status and its evidence/uncertainty, trade-in availability if verified, relevant changeover estimate and assumptions if supplied, event reason, and original direct link. Highlight TSS/Cyclespot local offers but still report good nationwide matches.

## 9. MQTT

Use configurable MQTT broker, authentication via environment variables, QoS 1 for listing events and non-retained event messages. Example topics:

- `motorcycles/trademe/new`
- `motorcycles/trademe/price_drop`
- `motorcycles/trademe/review`
- `motorcycles/trademe/status`
- `motorcycles/trademe/error`

Prefer source-agnostic internal events and configurable topic prefix so future dealer adapters fit. Include stable `event_id`, `listing_key`, `observed_at` and a predictable JSON schema. Retained service status is optional. Failed publish stays queued and retries safely. Do not falsely claim exactly-once delivery: MQTT consumers should deduplicate by `event_id`.

## 10. US aftermarket parts and DIY support

A major purchasing consideration is **cheap replacement parts**, often influenced by motorcycle popularity and supply in the **USA**. This belongs in a relatively static **model/generation knowledge database**, not repeated web research on every listing scan.

Track, with authoritative/reputable URLs and last-checked dates:

- Whether each exact generation/model is officially sold and widely supported in the US.
- Genuine service/workshop manual availability **to private owners**, correct edition/part number where verified.
- Dealer service support near Wellington and likely proprietary diagnostics requirements.
- Routine service parts: filters, brake pads/discs, chains/sprockets, seals/bearings, clutch components.
- More expensive parts: water pump, sensors, regulator, ABS components, dashboard, headlamp, body panels.
- US parts sources and aftermarket maturity, with compatibility cautions between US and NZ variants.
- Shipping, GST and currency impacts on total landed cost where reasonably known.

Do not invent numeric dependability scores, supply assurances, workshop manual part numbers or cross-generation compatibility. Model support should appear as a concise memo in alerts, not a fake per-listing LLM judgment. Update research manually or periodically with optional assisted tools. Initial model support entries: **Ninja 650 (2020+)** and **GSX-8R (2024+)**.

## 11. Optional LLM

Version 1 must be fully functional without an LLM. Add a swappable interface for a local Ollama model or external API *only for ambiguous descriptions*. Require constrained schema/JSON with `UNRESTRICTED/RESTRICTED/UNKNOWN`, evidence quotations/references, and an uncertainty reason. LLM cannot override objective exclusions without evidence, hallucinate missing specifications, or silently approve uncertain variants. Avoid paid calls for every record.

## 12. Configuration

Use YAML, environment variables for secrets, `.env.example` (not real secrets in git), with validation and defaults. Example:

```yaml
search:
  max_price_nzd: 12500
  max_odometer_km: 10000
  coverage: nationwide
  preferred_regions: [Wellington, Hutt Valley, Kapiti, Wairarapa, Manawatu]
  models:
    - {make: Kawasaki, model: Ninja 650, min_year: 2020, require_unrestricted: true}
    - {make: Suzuki, model: GSX-8R, min_year: 2024, require_unrestricted: true}
  sources:
    trademe: {enabled: true, search_urls: []}
    dealer_tss: {enabled: false, search_urls: []}
    dealer_cyclespot: {enabled: false, search_urls: []}
collector:
  mode: auto
  request_interval_seconds: 10
  max_concurrency: 1
  request_timeout_seconds: 30
  enable_browser_fallback: false
alerts:
  price_drop_nzd: 500
  price_drop_percent: 5
  notify_unknown_power: true
  notify_initial_results: false
mqtt:
  enabled: true
  host: localhost
  port: 1883
  topic_prefix: motorcycles
  qos: 1
database:
  path: /var/lib/motorcycle-monitor/listings.db
logging:
  level: INFO
  path: /var/log/motorcycle-monitor/monitor.log
llm:
  enabled: false
```

Search URLs must be manually validated for present-day Trade Me behaviour. Treat the dealer adapter URL list as initially optional rather than assuming a stable website.

## 13. CLI, scheduling and diagnostics

Provide a console command `motorcycle-monitor` with at least:

```bash
motorcycle-monitor scan
motorcycle-monitor scan --dry-run
motorcycle-monitor scan --notify-initial
motorcycle-monitor status
motorcycle-monitor listings
motorcycle-monitor listings --review
motorcycle-monitor history LISTING_ID
motorcycle-monitor test-mqtt
motorcycle-monitor validate-config
```

`--dry-run` must neither persist live data nor publish notifications. Implement a systemd **oneshot service and timer** scheduled daily at 08:00 Pacific/Auckland (document correct timezone handling). Use a lock to prevent concurrent scans. Log counts, source failures, invalid pages, parse schema changes and notification results; a 0-results successful scan must be distinguishable from blocked/faulty collection.

## 14. Tests

Use pytest and saved offline fixtures. Tests must run without visiting Trade Me. Minimum tests:

1. Full-power Ninja accepted; LAMS Ninja rejected; unknown-power Ninja reviewed.
2. GSX-8R accepted; GSX-8S rejected; Z650 and ZX-6R rejected.
3. Over-price/over-mileage/too-old rejected; missing critical data reviewed.
4. Current auction bid below budget does not qualify as a fixed-price offer.
5. New listing alerts once; unchanged repeats not alerted; valid price drop alerts; minor drop does not.
6. First scan creates baseline without a notification storm.
7. A relisting is suggested as a possible duplicate, not silently merged.
8. One transient request failure does not mark listings ended.
9. MQTT outage retains pending event; retry has stable event ID.
10. HTML/schema changes and HTTP 403/429 generate actionable diagnostics.
11. Dealer-and-Trade-Me duplicate retains both links but only one alert.
12. Trade-in quote and private sale scenario produce correct transparent changeover arithmetic.
13. Normalization of NZ dollar amounts, odometer units, dates and URLs.
14. Config validation, file locking and dry-run guarantee.

## 15. Deliverables

- Readable, typed Python 3.12+ code and `pyproject.toml`.
- Source adapters, normalization/classifier, SQLite migrations, outbox publisher, CLI.
- `README.md`, `config.example.yaml`, `.env.example` and example MQTT/Node-RED subscription documentation.
- systemd service and timer unit files.
- Tests, realistic fixture data, clear installation/upgrading/troubleshooting guidance.
- No Docker requirement; no paid API or LLM requirement for core functionality.

## 16. Implementation plan for Codex

**Stage 1: Acquisition proof of concept.** Create clean project structure. Validate provided search URLs and actual publicly accessible data structures; implement Trade Me adapter and parser. Demonstrate real extraction only where the website permits access; never fabricate selectors or pretend that an unverified parse succeeded. Provide offline fixtures and unit tests.

**Stage 2: Filtering and storage.** Implement precise model matching, power-state classification, database schema/history and baseline scan behaviour.

**Stage 3: MQTT and notification outbox.** Implement stable event IDs, deduplication and retry.

**Stage 4: Dealer/trade-in features.** Add dealer adapters or configuration as verified, cross-source deduplication, manual valuations, transparent changeover calculations and local dealer prioritisation.

**Stage 5: Aftermarket support and optional LLM.** Create model-support knowledge entries and optional evidence-bound LLM review, without complicating routine scraping.

**Stage 6: Unattended deployment.** systemd schedule, logs, health monitoring, complete regression suite and install instructions.

At each stage implement, run tests and report exactly what was verified. Do not proceed on invented website assumptions. Keep the utility maintainable and proportionate to monitoring two bike models.

## 17. Acceptance criteria

A clean Debian/Ubuntu LXC can install and run the monitor; verified accessible public listings are parsed accurately; restricted LAMS bikes are never silently accepted; price/odometer/year criteria are applied correctly; all uncertain power claims are visible; database history survives restarts; new matches and meaningful price reductions generate non-duplicated MQTT alerts; blocked collection produces a clear error; optional dealer trade-in estimates show changeover cost without invented figures; and all offline tests pass.
