The structured.html and manual.json fixtures are explicitly synthetic. They are
not claims about Trade Me's current schema or actual sale listings.

tss-*.html and cyclespot-*.html are minimal stock card excerpts fetched from the
public stock pages on 2026-10-13. Images, scripts, styles and encrypted contact
attributes have been removed. Only necessary fields and markup are preserved.
These cover Husqvarna Svartpilen/Suzuki UK110 and Aprilia Tuono/BMW GS, so tests
verify real extraction separately from synthetic eligible-bike filtering.

trademe-ninja.html and trademe-gsx.html retain only actual rendered count/card
markup from public category searches on 2026-10-13. Images, SVGs and unrelated
page content are removed. trademe-detail.html retains actual public JSON-LD
facts and price/ORC markup for listing 5915854398; its description is shortened
to a brief full-power excerpt and its image reference is removed.

tss-filter-settings.html keeps only actual public make choices and collection
metadata from the used stock page. tss-page2.json is a verified public new-stock
Suzuki/Road Sports second page, with unnecessary assets removed. The collection
adapter uses make-only filters and validates every page against reported totals.
