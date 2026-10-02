"""
Messaging abstraction.

Without a broker (default): everything runs through an in-process Bus that
mimics MQTT topic semantics, including `+` / `#` wildcards. The mock
generator and the FastAPI app both talk to this Bus, so the whole system
runs offline with zero setup.

With real ESP32s: set the VTB_MQTT_URL env var (e.g. mqtt://localhost:1883).
MqttBus wraps paho-mqtt 2.x with the identical publish/subscribe interface,
so nothing else in the codebase has to change.
"""
from __future__ import annotations
import asyncio
import json
import logging
from collections import defaultdict
from typing import Awaitable, Callable

Handler = Callable[[str, dict], Awaitable[None] | None]

log = logging.getLogger("vtb.bus")


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT topic filter matching: `+` matches one level, `#` the rest."""
    p_parts, t_parts = pattern.split("/"), topic.split("/")
    for i, p in enumerate(p_parts):
        if p == "#":
            return True
        if i >= len(t_parts) or (p != "+" and p != t_parts[i]):
            return False
    return len(p_parts) == len(t_parts)


async def _call(handler: Handler, topic: str, payload: dict):
    result = handler(topic, payload)
    if asyncio.iscoroutine(result):
        await result


class Bus:
    """Async in-memory pub/sub with MQTT-style topic filters."""

    def __init__(self):
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler):
        self._subscribers[topic].append(handler)

    def _handlers_for(self, topic: str) -> list[Handler]:
        return [h for pattern, hs in list(self._subscribers.items())
                if topic_matches(pattern, topic) for h in hs]

    async def publish(self, topic: str, payload: dict):
        for handler in self._handlers_for(topic):
            await _call(handler, topic, payload)


class MqttBus(Bus):
    """Same interface as Bus, backed by a real MQTT broker via paho-mqtt 2.x.
    paho runs its network loop on its own thread; incoming messages are
    handed to the asyncio loop with run_coroutine_threadsafe."""

    def __init__(self, broker_url: str):
        super().__init__()
        import paho.mqtt.client as mqtt
        from urllib.parse import urlparse

        parsed = urlparse(broker_url)
        self._host = parsed.hostname or "localhost"
        self._port = parsed.port or 1883
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if parsed.username:
            self._client.username_pw_set(parsed.username, parsed.password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def start(self, loop: asyncio.AbstractEventLoop):
        """Connect and start paho's network thread. Call from the app's lifespan."""
        self._loop = loop
        self._client.connect_async(self._host, self._port)
        self._client.loop_start()

    def stop(self):
        self._client.loop_stop()
        self._client.disconnect()

    def subscribe(self, topic: str, handler: Handler):
        super().subscribe(topic, handler)
        if self._client.is_connected():
            self._client.subscribe(topic)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        log.info("MQTT connected to %s:%s (%s)", self._host, self._port, reason_code)
        # (re)subscribe everything — also covers reconnects after a network drop
        for topic in self._subscribers:
            client.subscribe(topic)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.warning("dropping non-JSON message on %s", msg.topic)
            return
        if self._loop is None:
            return
        for handler in self._handlers_for(msg.topic):
            asyncio.run_coroutine_threadsafe(_call(handler, msg.topic, payload), self._loop)

    async def publish(self, topic: str, payload: dict):
        # The broker echoes our own publishes back to subscribers, so local
        # handlers are reached via _on_message — no direct dispatch here.
        self._client.publish(topic, json.dumps(payload))


def create_bus() -> Bus:
    from app.config import MQTT_BROKER_URL
    return MqttBus(MQTT_BROKER_URL) if MQTT_BROKER_URL else Bus()


# Single shared bus instance used across the app + mock generator.
bus = create_bus()
