"""QoS-1 outbox delivery; consumers deduplicate stable event IDs."""

import os
import threading
import time
from collections.abc import Callable

from .storage import Store

TOPICS = {
    "NEW_LISTING": "new",
    "PRICE_DROP": "price_drop",
    "REVIEW_REQUIRED": "review",
    "LISTING_REACTIVATED": "status",
    "LISTING_UNAVAILABLE": "status",
    "BASELINE_SUMMARY": "status",
    "SYSTEM_ERROR": "error",
}


class MQTTPublisher:
    def __init__(self, config: dict):
        self.config = config

    def __call__(self, topic: str, payload: str) -> None:
        import paho.mqtt.client as mqtt

        connected = threading.Event()
        status = []
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        def on_connect(client, userdata, flags, reason_code, properties):
            status.append(reason_code == 0)
            connected.set()

        client.on_connect = on_connect
        username = os.environ.get("MQTT_USERNAME")
        if username:
            client.username_pw_set(username, os.environ.get("MQTT_PASSWORD"))
        if self.config.get("tls", False):
            client.tls_set(ca_certs=os.environ.get("MQTT_CA_CERT") or None)
        client.connect(self.config["host"], self.config["port"], keepalive=30)
        client.loop_start()
        try:
            if not connected.wait(10) or not status or not status[0]:
                raise RuntimeError("MQTT connection rejected or timed out")
            message = client.publish(topic, payload, qos=1, retain=False)
            if message.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publish error {message.rc}")
            message.wait_for_publish(timeout=10)
            if not message.is_published():
                raise RuntimeError("MQTT PUBACK timed out")
        finally:
            client.disconnect()
            client.loop_stop()


def drain(
    store: Store, config: dict, publish: Callable[[str, str], None] | None = None
) -> dict:
    counts = {"delivered": 0, "failed": 0}
    if not config["mqtt"]["enabled"]:
        return counts
    publish = publish or MQTTPublisher(config["mqtt"])
    for row in store.db.execute(
        "SELECT * FROM notifications WHERE delivery_state='PENDING' ORDER BY created_at LIMIT 100"
    ).fetchall():
        topic = (
            config["mqtt"]["topic_prefix"].rstrip("/") + "/" + TOPICS[row["event_type"]]
        )
        try:
            publish(topic, row["payload"])
        except Exception as error:
            with store.db:
                store.db.execute(
                    "UPDATE notifications SET attempts=attempts+1,last_error=? WHERE event_id=?",
                    (str(error), row["event_id"]),
                )
            counts["failed"] += 1
            break  # Don't spend a full timeout per queued event during an outage.
        else:
            with store.db:
                store.db.execute(
                    "UPDATE notifications SET attempts=attempts+1,delivery_state='DELIVERED',last_error=NULL,delivered_at=? WHERE event_id=?",
                    (
                        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        row["event_id"],
                    ),
                )
            counts["delivered"] += 1
    return counts
