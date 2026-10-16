"""Compile purchase requirements once into reusable, transparent LLM screening.

An operational plan is a heuristic, not manufacturer specification evidence.
Literal model rules and bounded ordinary-small-engine estimates screen stock bikes.
There is no blanket 650cc cutoff. Explicit high output and racing/tuning exceptions
take priority over heuristic screening.
"""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import httpx

from .normalization import utc_now
from .secrets import credential

VERSION = 2
POLICY_KEYS = (
    "min_year",
    "max_price_nzd",
    "max_odometer_km",
    "requirements",
    "preferences",
    "coverage",
    "preferred_regions",
)
SYSTEM = """You are compiling a reusable operational motorcycle search plan for New Zealand.
Input is purchase requirements, not individual advertisements. Return JSON only:
{"summary":"brief operational strategy", "capacity_rules":[{"name":"Ordinary small stock engines", "max_engine_cc":250,"power_hp_upper":75,"confidence":"high","reason":"Ordinary stock 250cc-or-smaller engines fall below 80 hp; racing/tuned exceptions must remain for investigation."}], "rules":[
{"name":"family", "make":"Yamaha", "models":["MT-07","XSR700"],
"year_min":2017,"year_max":2026,"action":"screen_out",
"confidence":"high","power_hp_upper":76,
"reason":"Even unrestricted stock variants are below the required horsepower; distinguish MT-09"}],
"priority_models":[{"make":"Honda","model":"CBR650R","reason":"promising power/weight/seat; confirm NZ variant"}],
"queries":["Honda CBR650R non LAMS ABS New Zealand used"],
"cautions":["599/600/636 cc four-cylinder supersports can exceed 80 hp; never reject by cc alone"]}.
Produce up to 50 HIGH-CONFIDENCE low-power model-family rules covering common NZ stock.
Do not overlook scooters, minibikes, children's bikes, farm/trail bikes and singles:
Honda NSC110/Dio/PCX/Forza, Yamaha PW/TTR/WR/XT/NMAX/XMAX, Honda CRF/XR,
Suzuki DR/DR-Z/Burgman, Kawasaki KLX/KX, KTM EXC/SX/Adventure singles. Group
related low-power models in a rule rather than spending all rules on individual models.
For an 80 hp minimum, provide at least one capacity_rules entry for a conservative
ordinary-stock threshold (choose e.g. 125, 150 or 250 cc). max_engine_cc must be an
INTEGER and power_hp_upper a NUMBER STRICTLY BELOW 80. A threshold of 80 hp does
not screen anything and is invalid. Racing/two-stroke/tuned exceptions are handled
by the runtime. Do not omit a safe 125 cc ordinary-stock rule just because exceptional
racing engines exist. Do not put excluded models in priority_models.
Generic letter prefixes (PW, TTR, CRF, XR, DR, DR-Z, KLX, KX, EXC, SX) do NOT
match numbered models: explicitly enumerate complete aliases, e.g. CRF50F, CRF110F,
CRF125F, CRF150F, CRF230F, CRF250L, CRF450R. CRF1000/1100 Africa Twin is a HIGH
POWER exception: never exclude all Honda CRF models as one unqualified family.
Include a general capacity_rules predicate only when safely below the mandatory
power threshold. max_engine_cc MUST be at most 250, never a 650cc cutoff. Capacity
screening is heuristic and must exempt explicit high-power/racing/tuned machines.
Specific named aliases WITHOUT digits (such as Honda Dio) are valid; ambiguous
families spanning high-power models (such as Ninja, Duke, GSX) are not.
Each rule must identify a make and LITERAL, specific model aliases; never wildcard/regex,
blanket displacement cutoffs, generic '600', '650', 'Ninja', 'CB', 'GSX', or engine-size-only groups.
A screen_out rule is allowed ONLY when every stock full-power variant in its year scope
has horsepower below the user's mandatory minimum. Use conservative UPPER bounds in
MECHANICAL hp, not PS. If near the threshold, uncertain, variant-dependent or the family
has a more powerful exception, omit the exclusion or narrow aliases/year scope.
Do not exclude high-output 400/600/636 cc four-cylinder sports bikes merely for capacity.
Examples of distinct families to evaluate: Kawasaki Ninja 650 vs Ninja ZX-6R;
Yamaha MT-07 vs MT-09; Honda CB500F vs CB650R vs CBR600RR; Suzuki SV650 vs GSX-R600.
Identify up to 25 promising priority models satisfying most power/weight/seat/ABS requirements,
with year/variant caveats in reasons. A priority list is never a whitelist. Keep unknown
and unlisted models in discovery. Never assume non-LAMS or ABS from a model name.
Supply up to 8 targeted public search queries, including NZ location/price/year intent,
and up to 8 concise cautions about false exclusions and uncertain specifications.
Plan rules are disclosed as LLM screening estimates, not independently verified facts.
No credentials, URLs, executable code or invented evidence. Work from model-family knowledge.
Use only year scopes within the requested minimum year and the supplied maximum year.
If no mandatory power minimum exists, return an empty rules list.
Each reason at most 35 words; summary at most 80 words."""


def policy_fingerprint(search):
    policy = {key: search.get(key) for key in POLICY_KEYS}
    return hashlib.sha256(
        json.dumps([VERSION, policy], sort_keys=True).encode()
    ).hexdigest()


GENERIC_MODELS = {
    "ninja",
    "gsx",
    "cb",
    "cbr",
    "mt",
    "motorcycle",
    "bike",
    "scooter",
    "road",
    "sport",
    "enduro",
    "trail",
    "adventure",
    "duke",
    "tracer",
    "scrambler",
    "street",
    "tiger",
    "monster",
    "crf",
    "xr",
    "dr",
    "dr-z",
    "klx",
    "kx",
    "exc",
    "sx",
    "pw",
    "ttr",
    "wr",
    "xt",
}


def literal_model(value):
    return (
        isinstance(value, str)
        and 3 <= len(value) <= 45
        and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 /-]*", value))
        and bool(re.search(r"[a-z]", value, re.I))
        and value.lower().strip() not in GENERIC_MODELS
    )


def validate_plan(value, search):
    if not isinstance(value, dict) or not isinstance(value.get("summary"), str):
        raise ValueError("Invalid operational plan")
    if not all(
        isinstance(value.get(key), list)
        for key in ("rules", "priority_models", "queries", "cautions")
    ):
        raise ValueError("Invalid operational plan lists")
    rules = []
    minimum = search.get("requirements", {}).get("min_power_hp")
    for rule in value["rules"][:50]:
        if not isinstance(rule, dict):
            continue
        make = rule.get("make")
        raw_models = rule.get("models")
        models = (
            [model for model in raw_models if literal_model(model)]
            if isinstance(raw_models, list)
            else []
        )
        lower, upper = rule.get("year_min"), rule.get("year_max")
        ceiling = rule.get("power_hp_upper")
        if (
            rule.get("action") != "screen_out"
            or rule.get("confidence") != "high"
            or not isinstance(make, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z -]{1,30}", make)
            or not isinstance(models, list)
            or not models
            or len(models) > 30
            or not all(literal_model(model) for model in models)
            or type(lower) is not int
            or type(upper) is not int
            or not 1900 <= lower <= upper <= 2100
            or type(ceiling) not in (int, float)
            or minimum is None
            or not 0 < ceiling < minimum
            or not isinstance(rule.get("reason"), str)
        ):
            continue
        rules.append(
            {
                "name": str(rule.get("name", make))[:100],
                "make": make,
                "models": models,
                "year_min": max(lower, search["min_year"]),
                "year_max": upper,
                "power_hp_upper": ceiling,
                "action": "screen_out",
                "confidence": "high",
                "reason": rule["reason"][:500],
            }
        )
    priorities = []
    for item in value["priority_models"][:25]:
        if (
            isinstance(item, dict)
            and isinstance(item.get("make"), str)
            and literal_model(item.get("model"))
            and isinstance(item.get("reason"), str)
        ):
            priorities.append(
                {
                    "make": item["make"][:60],
                    "model": item["model"],
                    "reason": item["reason"][:500],
                }
            )
    excluded_aliases = {
        (rule["make"].lower(), re.sub(r"[^a-z0-9]", "", alias.lower()))
        for rule in rules
        for alias in rule["models"]
    }
    priorities = [
        item
        for item in priorities
        if (item["make"].lower(), re.sub(r"[^a-z0-9]", "", item["model"].lower()))
        not in excluded_aliases
    ]
    capacity_rules = []
    for rule in (
        value.get("capacity_rules", [])[:4]
        if isinstance(value.get("capacity_rules", []), list)
        else []
    ):
        if not isinstance(rule, dict):
            continue
        cc, ceiling = rule.get("max_engine_cc"), rule.get("power_hp_upper")
        if (
            type(cc) is int
            and 0 < cc <= 250
            and type(ceiling) in (int, float)
            and minimum is not None
            and 0 < ceiling < minimum
            and rule.get("confidence") == "high"
            and isinstance(rule.get("reason"), str)
        ):
            capacity_rules.append(
                {
                    "name": str(rule.get("name", "Small stock engines"))[:100],
                    "max_engine_cc": cc,
                    "power_hp_upper": ceiling,
                    "confidence": "high",
                    "reason": rule["reason"][:500],
                }
            )
    return {
        "capacity_rules": sorted(
            capacity_rules, key=lambda rule: rule["max_engine_cc"]
        ),
        "summary": value["summary"][:1000],
        "rules": rules,
        "priority_models": priorities,
        "queries": [q[:250] for q in value["queries"][:8] if isinstance(q, str)],
        "cautions": [q[:500] for q in value["cautions"][:8] if isinstance(q, str)],
    }


def plan_path(config):
    return Path(config["database"]["path"]).parent / "operational-plan.json"


def read_plan(config):
    """Read only; dashboard/CLI never trigger cloud calls or renew a plan."""
    if not config["llm"].get("plan_enabled"):
        return None
    try:
        value = json.loads(plan_path(config).read_text())
        if (
            value.get("fingerprint") != policy_fingerprint(config["search"])
            or value.get("version") != VERSION
            or value.get("status") != "ready"
        ):
            return None
        metadata = {
            key: value[key]
            for key in (
                "version",
                "status",
                "fingerprint",
                "generated_at",
                "model",
                "note",
            )
            if key in value
        }
        return {**metadata, **validate_plan(value, config["search"])}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def compile_plan(config, *, persist=True, client=None):
    """One bounded cloud call only when no plan matches the current requirements."""
    cached = read_plan(config)
    if cached:
        return cached
    if not config["llm"].get("enabled") or not config["llm"].get("plan_enabled"):
        return None
    owned = client is None
    client = client or httpx.Client(timeout=120, follow_redirects=False)
    phase = "credential"
    try:
        secret = credential("DEEPSEEK_API_KEY", config["llm"]["api_key_file"])
        context = {key: config["search"].get(key) for key in POLICY_KEYS}
        from datetime import date

        context["maximum_year"] = date.today().year + 1
        phase = "api"
        response = client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": "Bearer " + secret},
            timeout=120,
            json={
                "model": config["llm"]["model"],
                "thinking": {"type": "disabled"},
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": json.dumps(context)},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 9500,
            },
        )
        if response.status_code != 200:
            raise ValueError("Operational planner unavailable")
        phase = "response"
        choice = response.json()["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("Incomplete operational plan")
        phase = "validation"
        plan = validate_plan(json.loads(choice["message"]["content"]), config["search"])
        plan.update(
            version=VERSION,
            status="ready",
            fingerprint=policy_fingerprint(config["search"]),
            generated_at=utc_now(),
            model=config["llm"]["model"],
            note="LLM operational screening estimates; not verified manufacturer specifications. Unknown models remain eligible for research.",
        )
        phase = "persistence"
        if persist:
            target = plan_path(config)
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", dir=target.parent, prefix=".plan-", delete=False
            ) as handle:
                temporary = Path(handle.name)
                try:
                    json.dump(plan, handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temporary.chmod(0o600)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
        return plan
    except (OSError, ValueError, TypeError, KeyError, IndexError, httpx.HTTPError):
        # No guessed fallback rules: discovery/research still run normally.
        return {
            "status": "unavailable",
            "failure_stage": phase,
            "rules": [],
            "priority_models": [],
            "queries": [],
            "cautions": [],
            "summary": "Operational plan unavailable; ordinary evidence-based discovery continues.",
        }
    finally:
        if owned:
            client.close()


def model_matches(listing, make, model):
    text = " ".join(filter(None, [listing.make, listing.model, listing.title]))
    if not re.search(r"(?<![a-z])" + re.escape(make) + r"(?![a-z])", text, re.I):
        return False
    # Only literal aliases: allow normal model punctuation, keep suffix boundaries.
    characters = [re.escape(c) for c in model if c.isalnum()]
    expression = r"(?<![a-z0-9])" + r"[ -]*".join(characters) + r"(?![a-z0-9])"
    return bool(re.search(expression, text, re.I))


def screen(listing, search, facts):
    plan = search.get("_operational_plan") or {}
    minimum = search.get("requirements", {}).get("min_power_hp")
    if not minimum or plan.get("fingerprint") != policy_fingerprint(search):
        return None
    # Actual supported power wins over an LLM family estimate. A higher seller
    # claim stays in research rather than being falsely declared impossible.
    if facts.get("power_hp", {}).get("value") is not None:
        return None
    if listing.model_year is None:
        return None
    cc = listing.engine_cc
    advert = listing.title + "\n" + listing.description
    unusual = re.search(
        r"two[- ]stroke|2[- ]stroke|race[- ](?:only|bike)|racing motorcycle|competition|grand prix|gp250|250[- ]gp|turbo|supercharg|big[- ]bore|engine[- ]swap|tuned engine|modified engine",
        advert,
        re.I,
    )
    if unusual:
        return None
    if cc:
        for rule in plan.get("capacity_rules", []):
            if 0 < cc <= rule["max_engine_cc"] and rule["power_hp_upper"] < minimum:
                return {
                    "fingerprint": plan["fingerprint"],
                    "rule": rule["name"],
                    "reason": rule["reason"],
                    "estimated_power_hp_upper": rule["power_hp_upper"],
                    "verified": False,
                    "note": "Operational small-engine screening estimate; high-output and racing/modified exceptions remain for investigation. Visible in All tracked.",
                }
    for rule in plan.get("rules", []):
        if (
            rule["year_min"] <= listing.model_year <= rule["year_max"]
            and rule["power_hp_upper"] < minimum
            and any(
                model_matches(listing, rule["make"], model) for model in rule["models"]
            )
        ):
            return {
                "fingerprint": plan["fingerprint"],
                "rule": rule["name"],
                "reason": rule["reason"],
                "estimated_power_hp_upper": rule["power_hp_upper"],
                "verified": False,
                "note": "Screened out using a reusable LLM model-family estimate; not a researched specification. Visible in All tracked.",
            }
    return None


def preferred_model(listing, search):
    return any(
        model_matches(listing, item["make"], item["model"])
        for item in search.get("_operational_plan", {}).get("priority_models", [])
    )
