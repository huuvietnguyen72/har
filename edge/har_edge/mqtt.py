"""Tạo client paho-mqtt 2.x dùng chung cho các dịch vụ."""
import json
import logging
import uuid
from collections.abc import Callable

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)


def make_client(cfg, name: str, topics: list[tuple[str, int]], on_json: Callable[[str, dict], None] | None = None) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{name}-{uuid.uuid4().hex[:6]}")
    if cfg.mqtt_user:
        client.username_pw_set(cfg.mqtt_user, cfg.mqtt_password)
    client.reconnect_delay_set(1, 30)

    def on_connect(c, userdata, flags, reason, props):
        if reason.is_failure:
            log.error("MQTT kết nối thất bại: %s", reason)
            return
        log.info("MQTT đã kết nối %s:%s", cfg.mqtt_host, cfg.mqtt_port)
        for t, q in topics:
            c.subscribe(t, qos=q)

    def on_message(c, userdata, msg):
        if on_json is None:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("Bỏ gói không phải JSON trên %s", msg.topic)
            return
        try:
            on_json(msg.topic, payload)
        except Exception:
            log.exception("Lỗi xử lý %s", msg.topic)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(cfg.mqtt_host, cfg.mqtt_port, keepalive=30)
    return client


def topic_parts(topic: str) -> tuple[str, str]:
    """'har/har01/imu' -> ('har01', 'imu')"""
    parts = topic.split("/")
    return (parts[1], parts[2]) if len(parts) >= 3 else ("", "")


def publish_json(client: mqtt.Client, topic: str, payload: dict, qos: int = 0, retain: bool = False) -> None:
    client.publish(topic, json.dumps(payload, separators=(",", ":")), qos=qos, retain=retain)
