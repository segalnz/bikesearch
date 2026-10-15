# MQTT and Node-RED

Set `mqtt.enabled: true`, your broker host/port, and export `MQTT_USERNAME` and
`MQTT_PASSWORD` (or use the service EnvironmentFile). The application does not
implicitly read .env files. Enable `mqtt.tls: true` for TLS; use port 8883 and an
optional MQTT_CA_CERT PEM path. Certificate verification stays enabled.

Subscribe with a Node-RED MQTT input node to `motorcycles/#`, QoS 1. Events use
`new`, `price_drop`, `review`, `status` and `error` suffixes and are non-retained.
Use a JSON node, then deduplicate **before** downstream actions by event_id.
A Function node may use:

```javascript
const id = msg.payload.event_id;
if (!id) return null;
const seen = context.get('seen') || [];
if (seen.includes(id)) return null;
seen.push(id);
context.set('seen', seen.slice(-2000));
return msg;
```

Configure persistent Node-RED context storage if deduplication must survive
restarts. The bounded example is suitable for this low-volume service; choose a
larger/durable ID store if delayed redelivery might exceed that window.

Payload shape:

```json
{
  "schema_version": 1,
  "event_id": "stable UUID",
  "event_type": "NEW_LISTING",
  "listing_key": 1,
  "observed_at": "UTC ISO timestamp",
  "reason": "NEW_LISTING",
  "listing": {"title": "...", "source_urls": ["https://..."], "power_status": "UNRESTRICTED", "power_evidence": "Explicit evidence..."},
  "model_support": {"memo": "...", "last_checked": "2026-10-13"},
  "changeover": {"changeover_nzd": null, "unknowns": ["..."]}
}
```

The full listing object contains year, mileage, fixed-price type and value,
location, seller/dealer, preferred dealer, evidence and trade-in availability.
A baseline summary uses `counts` and `listings` instead of a single listing.
Review alerts include explicit reasons. LISTING_UNAVAILABLE events use the
status topic and label inferred absence; they do not claim a confirmed sale. Display review and confirmed opportunities
separately. All source links are validated against configured host allowlists.

`test-mqtt` publishes an actual non-retained test status message. `publish-pending`
retries queued events under the same lock as scans. A successful PUBACK marks
delivery; crashes between PUBACK and the database update may redeliver the same
stable event ID. This is **at-least-once**, not exactly-once delivery. Disabled
MQTT leaves the outbox queued; turning it on publishes historical queued events.
