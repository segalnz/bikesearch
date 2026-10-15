# Verification history

## Broad search and showcase — 16 October 2026

- 178 offline tests pass under Python 3.12; Ruff lint/format and JavaScript syntax checks pass.
- All-model criteria validate, including strict wet-weight preference under 210 kg, 225 kg maximum, ABS, non-LAMS, mileage/year/price and review of missing specifications.
- Independent inventory extraction was exercised against live public Courtesy, Maidstone, Langlands, THS Moto, Colemans, Cooks Honda and Turners pages. Counts are acquisition checks, not claims of complete national stock.
- The supplied DeepSeek credential authenticated successfully. The available model list was checked; one non-thinking JSON advisory review succeeded using `deepseek-flash`. No credential values were displayed.
- Brave/Tavily contracts are tested with mocked responses; live indexed API execution needs a separate provider credential. Some automated public engine probes returned challenges/rate limits; ordinary user browsing was not tested or claimed to be blocked.
- Desktop and 390 px mobile offline demo checks verified candidate/match/review filters, search, fictional-data notice, no JavaScript errors and no horizontal overflow. The README screenshot contains fictional inventory only.
- Publication guard and deployment-archive checks pass; keys, environment files, databases and local profiles are excluded. Mixed local credentials are parsed by service type, so GitHub access never transfers to the LXC.
- CI is configured for Python 3.11, 3.12 and 3.13 with pinned GitHub Action commits and read-only repository permissions. [Published CI](https://github.com/segalnz/bikesearch/actions/runs/38814462180) passed on all three versions for application commit `0ced6c6`.

- Final live LXC deployment `38cd892c4586` completed with a fresh scan, dashboard restart and enabled daily timer. The dashboard API verified the deployed criteria and reported 0 confirmed available matches and 480 candidates needing review. These are dated results, not verified recommendations.
- Health records cover all ten collection sources plus the publisher. Saved inventory includes 34 advisory DeepSeek reviews; other candidates remain pending within the configured review budget. Unsupported model quotations are removed, and one malformed candidate response does not disable subsequent reviews.

Earlier checks below document the narrower versions; their counts and deployment state are historical.

## Initial implementation — 13 October 2026

- Python 3.12.3, using the project `.venv`; dependency consistency check passed.
- 83 offline pytest tests passed. Ruff checks passed and modules compiled.
- Python 3.11 compatibility additionally verified using a fresh Python 3.11.17
  virtualenv: application/test/browser installation, all 83 tests, module
  compilation, configuration validation, Playwright version command and
  dependency consistency check passed. Minimum package version is now 3.11.
- Example configuration validates with all three sources enabled.
- systemd calendar validation confirms 08:00 Pacific/Auckland, with the next
  occurrence at 08:00 NZDT on 14 October (19:00 UTC on 13 October).

Live collection used public pages without an account. A full dry-run collected
27 Trade Me search results, 29 TSS Suzuki/Kawasaki bikes across all new/used
result pages, and 27 Cyclespot used/new-search results. No source errors occurred.
The dry-run did not create its configured database or publish MQTT messages.

Live detail checks confirmed asking price, model year, odometer, seller and
explicit full-power advert evidence. The exact model for one advert is stated
in its search subtitle rather than headline; a targeted current-detail check
also verified that case after fixing subtitle extraction. Five advert-supported
Ninja 650 offers met the configured price/year/mileage/power rules in the checked
inventory. This is a dated acquisition check, not a guarantee about future stock.

Offline checks cover power conflicts and negation, excluded models, missing
facts, price/year/mileage limits, current bids, initial baseline summaries,
unchanged/repeated observations, meaningful price drops, tracking-query changes,
reactivation, suggested relistings, exact cross-source references, history after
restart, stable outbox IDs and simulated MQTT failures, HTTP 403/429, malformed
pages, public dealer pagination/count guards, config, file locks, dry-run,
valuation arithmetic and financial ranking.

MQTT was tested through the outbox's simulated publisher failures and retries;
no connection was made to the owner's broker. No systemd service was installed
on this development host and no changes were made to the target Proxmox LXC.
The application, unit files and virtualenv deployment instructions are ready for
that environment once its broker/configuration are supplied.

Availability and readable-results update: 92 tests pass under Python 3.11 and
3.12. Checks include migration from schema 1 to 2, spaced missing observations,
failed-scan and search-scope resets, retention of history, protection of bikes
still active on another source, returning bikes on both existing/new exact
sources, suppression of irrelevant unavailable alerts, and readable listings
with a backwards-compatible --json option. Timer units remain daily oneshots;
the running timer provides unattended scheduling between scans.

Desktop dashboard update: 99 tests pass, including read-only dashboard reads
during an active SQLite write transaction, uninitialized database handling,
visible database errors, packaged asset responses, safe listing links, history
and rejection of mutation requests. Desktop (1280 px) and mobile (390 px) browser
checks verified filters, search, history, empty states, responsive layout and no
JavaScript errors. HTML/CSS/JS assets were verified in the built wheel. The
separate dashboard systemd unit is ready for the LXC; it has not been installed
on the user's container from this development workspace.

Regional search update (14 October 2026): 121 tests pass under Python 3.11.
The Wellington Ninja preset validates without writing deployment log paths.
Checks cover named corridor towns, out-of-area rejection, ambiguous location
review, all years/prices, strictly under 10,000 km, full-power evidence and
reevaluation of saved results when requirements change. No live inventory scan
or remote LXC configuration change was performed for this update.

One-command redeployment update (14 October 2026): 127 tests pass under Python
3.11. Checks include criteria merging without overwriting broker/database/source
settings, archive exclusion of credentials/runtime files, packaged dashboard and
installer files, atomic config permissions, SQLite backup/history preservation,
systemd restart/rescan sequencing and rollback after installation failure.
Fresh scans bypass cached HTTP responses. The deployment archive was generated
locally; SSH/systemd orchestration was tested with simulated LXC commands. No
live redeployment had been performed at that stage because the LXC SSH address
was not yet supplied.

Live LXC deployment (14 October 2026): deployed revision `8a0a4ab48273` to
`root@LXC_IP`. Installation in the existing Python 3.11 virtualenv and
configuration validation succeeded. The dashboard restarted, the fresh scan
completed successfully, and the installer verified the dashboard deployment ID
and Wellington Ninja criteria through its API: 1 available match, 0 needing
review. Dashboard: http://LXC_IP:8765/. A backup was retained at
`/var/lib/motorcycle-monitor/deploy-backups/20261013T201450Z-8a0a4ab48273`.
The local deployment target and preset are saved in ignored `.deploy.local.json`.
