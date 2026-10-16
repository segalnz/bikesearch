"use strict";
let state = { listings: [], runs: [] };
let filter = "candidates";
let timer;
let busy = false;
const money = (value) =>
  value == null
    ? "Unknown"
    : new Intl.NumberFormat("en-NZ", {
        style: "currency",
        currency: "NZD",
        maximumFractionDigits: 0,
      }).format(value);
const when = (value) =>
  value
    ? new Intl.DateTimeFormat("en-NZ", {
        timeZone: "Pacific/Auckland",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(value))
    : "Not yet seen";
const labels = {
  candidates: "Potential candidates",
  matches: "Available matches",
  review: "Candidates needing review",
  unassessed: "Unassessed discoveries",
  unavailable: "Unavailable / uncertain",
  all: "All tracked listings",
};
const sourceNames = {
  trademe: "Trade Me",
  dealer_tss: "TSS Motorcycles",
  dealer_cyclespot: "Cyclespot Wellington",
  publisher: "MQTT delivery",
};
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = String(text);
  return node;
};
const relevant = (item) => item.classification !== "REJECTED";
const candidate = (item) =>
  relevant(item) &&
  item.evidence?.suitability?.candidate_status !== "unassessed";
const active = (item) => item.listing_status === "ACTIVE";
function fact(label, value) {
  const node = el("div", "fact");
  node.append(el("dt", null, label), el("dd", null, value));
  return node;
}
function availability(item) {
  if (item.listing_status === "ENDED") return "Ended";
  if (item.listing_status === "UNKNOWN")
    return item.evidence?.availability?.status === "NOT_SEEN"
      ? "No longer seen available"
      : "Availability uncertain";
  if (item.evidence?.suitability?.candidate_status === "unassessed")
    return "Unassessed discovery";
  return item.classification === "REVIEW"
    ? "Needs review"
    : item.classification === "REJECTED"
      ? "Filtered out"
      : "Available match";
}
function card(item) {
  const node = el("article", "card");
  const top = el("div", "card-top");
  const cls = !active(item)
    ? "unavailable"
    : item.classification === "REVIEW"
      ? "review"
      : item.classification === "REJECTED"
        ? "rejected"
        : "";
  top.append(el("span", "badge " + cls, availability(item)));
  if (item.preferred_dealer)
    top.append(el("span", "local", "Preferred local dealer"));
  node.append(top, el("h3", null, item.title));
  const fixed = ["ASKING", "BUY_NOW"].includes(item.price_type);
  const price = el(
    "div",
    "price",
    fixed && item.asking_price_nzd != null
      ? money(item.asking_price_nzd)
      : "Price unconfirmed",
  );
  price.append(
    el(
      "span",
      "price-type",
      {
        ASKING: "Asking price",
        BUY_NOW: "Buy now",
        CURRENT_BID: "Auction · fixed price unknown",
        POA: "Price on application",
        UNKNOWN: "No confirmed purchase price",
      }[item.price_type] || item.price_type,
    ),
  );
  node.append(price);
  const horsepower = item.evidence?.suitability?.facts?.power_hp;
  const facts = el("dl", "facts");
  facts.append(
    fact("Model year", item.model_year ?? "Unknown"),
    fact(
      "Odometer",
      item.odometer_km == null
        ? "Unknown"
        : new Intl.NumberFormat("en-NZ").format(item.odometer_km) + " km",
    ),
    fact("Location", item.location || "Unknown"),
    fact(
      "Engine power",
      horsepower == null
        ? "Unconfirmed"
        : horsepower.value +
            " hp · " +
            (horsepower.kind === "manufacturer_research"
              ? "Manufacturer specification"
              : "Advert claim"),
    ),
    fact("Seller", item.dealer_name || item.seller_name || "Unknown"),
    fact(
      "On-road costs",
      item.orc_nzd === 0
        ? "Included"
        : item.orc_nzd == null
          ? "Unknown"
          : money(item.orc_nzd),
    ),
    fact(
      "Trade-in",
      { YES: "Verified available", NO: "Not available", UNKNOWN: "Unverified" }[
        item.trade_in_available
      ] || "Unverified",
    ),
  );
  node.append(facts);
  if (horsepower?.source_url) {
    try {
      const url = new URL(horsepower.source_url);
      if (url.protocol === "https:") {
        const source = el("a", null, "Power specification source");
        source.href = url.href;
        source.target = "_blank";
        source.rel = "noopener noreferrer";
        node.append(source);
      }
    } catch {}
  }
  const power = el("div", "power");
  power.append(
    el(
      "strong",
      null,
      "LAMS / restriction status: " + item.power_status.toLowerCase(),
    ),
    el("span", null, item.power_evidence || "No supporting evidence recorded."),
  );
  node.append(power);
  const suitability = item.evidence?.suitability;
  if (suitability) {
    const panel = el("details");
    panel.append(
      el(
        "summary",
        null,
        "Requirements & preferences · " +
          suitability.preference_matches +
          " preferences met",
      ),
    );
    for (const check of suitability.preferences || [])
      panel.append(
        el(
          "p",
          null,
          check.label +
            ": " +
            {
              preferred: "Preferred",
              acceptable: "Within consideration",
              unknown: "Unconfirmed",
            }[check.status] +
            (check.value == null ? "" : " (" + check.value + ")"),
        ),
      );
    for (const [field, fact] of Object.entries(suitability.facts || {})) {
      const row = el(
        "p",
        null,
        field.replaceAll("_", " ") + ": " + fact.value + " — " + fact.quotation,
      );
      if (fact.source_url) {
        try {
          const url = new URL(fact.source_url);
          if (url.protocol === "https:") {
            const link = el("a", null, " Manufacturer source");
            link.href = url.href;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            row.append(link);
          }
        } catch {
          /* Invalid evidence links are not rendered. */
        }
      }
      panel.append(row);
    }
    const research = item.evidence?.model_research;
    if (research)
      panel.append(
        el(
          "p",
          null,
          "Model research: " + research.status + ". " + research.note,
        ),
      );
    panel.append(el("p", null, suitability.note));
    node.append(panel);
  }
  const ai = item.evidence?.ai_review;
  if (ai) {
    const panel = el("details");
    panel.append(
      el("summary", null, "DeepSeek research guidance · " + ai.status),
      el("p", null, ai.summary),
    );
    for (const check of ai.checks || [])
      panel.append(
        el(
          "p",
          null,
          check.criterion +
            ": " +
            check.assessment +
            (check.quotation ? " — Advert: “" + check.quotation + "”" : ""),
        ),
      );
    if (ai.note) panel.append(el("p", null, ai.note));
    node.append(panel);
  }
  if (item.rejection_reasons?.length) {
    const box = el("div", "reason");
    for (const reason of item.rejection_reasons)
      box.append(el("p", null, reason));
    node.append(box);
  }
  if (!active(item) && item.evidence?.availability?.reason)
    node.append(el("div", "reason", item.evidence.availability.reason));
  const cost = item.changeover;
  if (cost?.changeover_nzd != null) {
    const box = el("div", "changeover");
    box.append(
      el("strong", null, "Changeover " + money(cost.changeover_nzd)),
      el(
        "span",
        null,
        `Price + ${money(cost.orc_nzd)} ORC + ${money(cost.expenses_nzd)} expenses − ${money(cost.valuation.value_nzd)} allowance/proceeds (${cost.valuation.basis}, ${cost.valuation.quote_date || "undated"}; ${cost.valuation.provenance || "provenance unknown"}).`,
      ),
    );
    node.append(box);
  } else
    node.append(
      el(
        "div",
        "changeover",
        "Changeover not calculated · " +
          (cost?.unknowns?.join(", ") || "no valuation supplied"),
      ),
    );
  const links = el("div", "links");
  for (const value of item.source_urls || []) {
    let url;
    try {
      url = new URL(value);
    } catch {
      continue;
    }
    if (!["http:", "https:"].includes(url.protocol)) continue;
    const link = el(
      "a",
      null,
      url.hostname === "trademe.co.nz" ||
        url.hostname.endsWith(".trademe.co.nz")
        ? "View on Trade Me ↗"
        : "View source listing ↗",
    );
    link.href = value;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    links.append(link);
  }
  node.append(
    links,
    el("div", "seen", "Last seen " + when(item.last_seen_utc)),
  );
  const history = el("details");
  history.append(el("summary", null, "Price & availability history"));
  const historyBody = el("div");
  history.append(historyBody);
  history.addEventListener("toggle", async () => {
    if (!history.open || history.dataset.loaded) return;
    historyBody.textContent = "Loading history…";
    try {
      const response = await fetch(
        "/api/history?id=" +
          encodeURIComponent(item.source + ":" + item.listing_id),
      );
      const data = await response.json();
      if (!response.ok) throw Error(data.error || "History unavailable");
      const rows = data.observations || [];
      historyBody.replaceChildren();
      const table = el("table", "history-table");
      const head = el("tr");
      for (const text of ["Observed (NZ)", "Price", "Mileage", "Availability"])
        head.append(el("th", null, text));
      const thead = el("thead");
      thead.append(head);
      const tbody = el("tbody");
      table.append(thead, tbody);
      for (const observation of rows.slice().reverse()) {
        const row = el("tr");
        for (const text of [
          when(observation.observed_at),
          money(observation.asking_price_nzd),
          observation.odometer_km == null
            ? "Unknown"
            : observation.odometer_km.toLocaleString("en-NZ") + " km",
          observation.listing_status === "UNKNOWN"
            ? "Not confirmed"
            : observation.listing_status.toLowerCase(),
        ])
          row.append(el("td", null, text));
        tbody.append(row);
      }
      historyBody.append(
        rows.length ? table : el("p", null, "No observations recorded."),
      );
      history.dataset.loaded = "true";
    } catch (error) {
      historyBody.textContent = error.message;
    }
  });
  node.append(history);
  if (item.model_support?.memo) {
    const support = el("details");
    support.append(
      el("summary", null, "Parts & workshop support"),
      el("p", null, item.model_support.memo),
      el(
        "p",
        null,
        "Research checked " +
          (item.model_support.last_checked || "not yet verified"),
      ),
    );
    node.append(support);
  }
  return node;
}
function render() {
  const listings = state.listings || [];
  const plan = state.operational_plan;
  const planPanel = document.querySelector("#operational-plan");
  planPanel.hidden = plan?.status !== "ready";
  const planContent = document.querySelector("#operational-plan-content");
  planContent.replaceChildren();
  if (plan?.status === "ready") {
    planContent.append(
      el("p", null, plan.summary),
      el(
        "p",
        null,
        "Generated " +
          when(plan.generated_at) +
          ". Reused until your requirements change. Screening rules are LLM estimates; specifications remain separate.",
      ),
    );
    for (const rule of plan.capacity_rules || [])
      planContent.append(
        el(
          "p",
          null,
          "Small-engine screening: ordinary stock engines up to " +
            rule.max_engine_cc +
            " cc; estimated maximum " +
            rule.power_hp_upper +
            " hp. " +
            rule.reason +
            " Racing, modified and explicit high-output exceptions remain for investigation.",
        ),
      );
    for (const rule of plan.rules || [])
      planContent.append(
        el(
          "p",
          null,
          "Screen out: " +
            rule.make +
            " " +
            rule.models.join(" / ") +
            " (" +
            rule.year_min +
            "–" +
            rule.year_max +
            "), estimated maximum " +
            rule.power_hp_upper +
            " hp. " +
            rule.reason,
        ),
      );
    planContent.append(
      el(
        "p",
        null,
        "Prioritize: " +
          (plan.priority_models || [])
            .map((item) => item.make + " " + item.model)
            .join(", "),
      ),
    );
    for (const caution of plan.cautions || [])
      planContent.append(el("p", null, caution));
  }
  if (state.criteria_summary)
    document.querySelector("#criteria").textContent =
      state.criteria_summary.join(" · ");
  document.querySelector("#count-matches").textContent = listings.filter(
    (item) => active(item) && item.classification === "ACCEPTED",
  ).length;
  document.querySelector("#count-review").textContent = listings.filter(
    (item) =>
      active(item) && candidate(item) && item.classification === "REVIEW",
  ).length;
  document.querySelector("#count-unavailable").textContent = listings.filter(
    (item) => !active(item) && relevant(item),
  ).length;
  document.querySelector("#count-total").textContent = listings.length;
  const query = document.querySelector("#search").value.toLowerCase().trim();
  const visible = listings.filter(
    (item) =>
      (filter === "all" ||
        (filter === "candidates" && active(item) && candidate(item)) ||
        (filter === "matches" &&
          active(item) &&
          item.classification === "ACCEPTED") ||
        (filter === "review" &&
          active(item) &&
          candidate(item) &&
          item.classification === "REVIEW") ||
        (filter === "unassessed" &&
          active(item) &&
          item.evidence?.suitability?.candidate_status === "unassessed") ||
        (filter === "unavailable" && !active(item) && relevant(item))) &&
      (!query ||
        [
          item.title,
          item.model,
          item.location,
          item.dealer_name,
          item.seller_name,
        ].some((value) =>
          String(value || "")
            .toLowerCase()
            .includes(query),
        )),
  );
  document.querySelector("#list-title").textContent = labels[filter];
  document.querySelector("#list-count").textContent =
    visible.length + " " + (visible.length === 1 ? "bike" : "bikes");
  const container = document.querySelector("#listings");
  container.replaceChildren(...visible.map(card));
  if (!visible.length)
    container.append(
      el(
        "div",
        "empty",
        !state.initialized
          ? "No saved results yet. The background scan will populate this page."
          : query
            ? "No bikes match this search."
            : filter === "matches"
              ? "No confirmed available matches right now. Check Needs review or Collection health below."
              : "No listings in this view.",
      ),
    );
  const recent = new Map();
  for (const run of state.runs || [])
    if (!recent.has(run.adapter)) recent.set(run.adapter, run);
  const runs = document.querySelector("#runs");
  runs.replaceChildren();
  for (const [source, run] of recent) {
    const box = el("div", "run");
    box.append(
      el(
        "span",
        "badge " + (run.outcome === "ERROR" ? "rejected" : ""),
        run.outcome === "ERROR" ? "Collection failed" : "Successful",
      ),
      el(
        "strong",
        null,
        sourceNames[source] || state.source_labels?.[source] || source,
      ),
      el("p", null, when(run.finished_at)),
    );
    const details = run.details || {};
    if (details.error) box.append(el("p", null, details.error));
    else if (details.parsed != null)
      box.append(
        el(
          "p",
          null,
          `${details.parsed} parsed · ${details.accepted || 0} matches · ${details.review || 0} review`,
        ),
      );
    if (details.warning) box.append(el("p", "reason", details.warning));
    runs.append(box);
  }
  if (!recent.size)
    runs.append(el("p", null, "No completed collection runs recorded yet."));
  document.querySelector("#outbox").textContent = state.mqtt_enabled
    ? `${state.pending_events || 0} queued notifications`
    : "MQTT disabled · saved results remain available";
}
async function refresh() {
  if (busy) return;
  // Keep an open history panel stable while the user reads it; manual refresh still works.
  busy = true;
  const button = document.querySelector("#refresh");
  button.disabled = true;
  const message = document.querySelector("#message");
  try {
    const response = await fetch("/api/results", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw Error(data.error || "Results unavailable");
    if (state.deployment_id && state.deployment_id !== data.deployment_id) {
      window.location.reload();
      return;
    }
    state = data;
    render();
    document.querySelector("#updated").textContent =
      "Refreshed " +
      when(data.generated_at) +
      (data.deployment_id && data.deployment_id !== "development"
        ? " · " + data.deployment_id.slice(0, 7)
        : "");
    message.className = "";
    message.textContent = data.demo
      ? "Offline showcase · all bikes, sellers and prices are fictional. No external services are called."
      : data.initialized
        ? ""
        : "Waiting for the first saved scan. Dry-runs do not save listings.";
  } catch (error) {
    message.className = "error";
    message.textContent =
      "Could not refresh results: " +
      error.message +
      ". Previously loaded results remain visible.";
  } finally {
    busy = false;
    button.disabled = false;
    clearTimeout(timer);
    timer = setTimeout(
      () => {
        if (document.querySelector("details[open]")) {
          timer = setTimeout(refresh, 60000);
        } else refresh();
      },
      Math.max(15, state.refresh_seconds || 60) * 1000,
    );
  }
}
document.querySelector("#refresh").addEventListener("click", refresh);
document.querySelector("#search").addEventListener("input", render);
for (const button of document.querySelectorAll("[data-filter]"))
  button.addEventListener("click", () => {
    filter = button.dataset.filter;
    for (const sibling of document.querySelectorAll("[data-filter]")) {
      const selected = sibling === button;
      sibling.classList.toggle("selected", selected);
      sibling.setAttribute("aria-pressed", String(selected));
    }
    render();
  });
refresh();
