# Acquisition verification — 13 October 2026

The supplied Trade Me category URL was checked directly:
https://www.trademe.co.nz/a/motors/motorbikes/motorbikes

Ordinary HTTP returned 200 with an Angular app shell. It did not contain listing
cards or listing search state. Ordinary, unmodified headless Chromium rendered
public listings without login. Using the visible category keyword search input
and Enter produced these actual URLs:

- https://www.trademe.co.nz/a/motors/motorbikes/motorbikes/search?search_string=Ninja%20650
- https://www.trademe.co.nz/a/motors/motorbikes/motorbikes/search?search_string=GSX%208R

The observed searches showed 18 and 9 results respectively. These are time-bound
observations, not promises about future inventory. The fixture excerpts preserve
the observed card structure, current/buy-now/asking labels and factual values.
Search is nationwide. Model spelling variants are filtered locally; broader
validated search URLs can be added without code changes. Unsupported pagination
fails visibly rather than silently claiming nationwide completeness.

A Ninja detail page was inspected with listing ID 5915854398. Its public JSON-LD
provided year, mileage, seller and engine size; HTML confirmed an asking price of
NZ$11,899, excluded ORC and explicit full-power title/description evidence. The
parser does not classify an arbitrary JSON-LD Offer as a fixed-price auction
purchase: Trade Me detail price classification also requires the explicit UI
label. A generic trade-in enquiry button remains UNKNOWN trade-in availability.

TSS used-stock HTTP: https://tssmotorcycles.co.nz/used-motorcycles-wellington/
Actual `.e-loop-item.type-motorcycles`, heading links and labeled attributes were
inspected. Cyclespot HTTP:
https://cyclespotwellington.co.nz/used/view-all-used-stock/
Actual `#listCars .car-wrapper`, quick-view metadata, price and specs were checked.
Both pages were accessible without accounts. Dealer identity/location verified
from https://tssmotorcycles.co.nz/ and
https://cyclespotwellington.co.nz/contacts/. “Cycleworks” is not treated as an
alias without further evidence. Kawasaki franchise status was not assumed.

Trade Me terms currently prohibit unauthorised automated scraping:
https://help.trademe.co.nz/hc/en-us/articles/360007001532-Trade-Me-site-terms-and-conditions
This project is personal research without accounts, republication, messaging or
purchasing. Operators remain responsible for use of the sources. HTTP 403/429 or
explicit challenges stop collection for that source. Native saved-search alerts
or manual normalized JSON imports remain the fallback. No evasion is provided.

Browser rendering is optional but needed for Trade Me's currently observed app
shell. It uses ephemeral browser contexts, never an account profile. Images,
media, fonts, styles and external analytics are blocked to avoid downloading
seller photos. No identity spoofing, CAPTCHA solving, proxies or login automation.
Top-level page acquisitions share the serial 10-second pacing and 30-page budget;
the browser has a separate 400-resource budget per page for app scripts and data.
Resources needed to render the app load normally; max_concurrency describes page
acquisitions, not Chromium's internal script fetches. The CSP reporting endpoint
occasionally returned 429 during inspection; it is not a listing acquisition
endpoint. Listing/document/API 403/429 still abort the source.

TSS's initial six-card HTML is incomplete: public filter metadata reported 29
used and 72 new bikes. Normal UI filtering was inspected, and the exact public
Jet Smart Filters POST fields were verified. The site's published JavaScript at
`/wp-content/plugins/jet-smart-filters/assets/js/public.js?ver=3.7.1` supplies the
`paged` parameter; a page-2 request returned page 2 and distinct cards. The adapter
reads current provider/query/settings/term IDs from each configured page rather
than inventing them. It filters the two configured makes, follows every reported
page and validates total counts and identities before committing. A live check
collected all 29 Suzuki/Kawasaki bikes across new and used stock in nine paced
requests. None met the current criteria.

Cyclespot's unfiltered new inventory has eight pages. The visible public GET
search form was inspected to obtain keyword searches instead of treating its
first page as complete. New-stock searches use broad Ninja and GSX terms; used
stock currently fits on one page. Unsupported future pagination fails visibly.
Dealer detail enhancement is not configured, so plausible cards lacking power
evidence go to review. Similar bikes are suggested for manual duplicate review;
only an exact shared source URL or an explicit owner-verified `verified_identity`
merges cross-site identities. Do not infer bike identity solely from similar
titles, dealer names or shared numeric URL segments.
