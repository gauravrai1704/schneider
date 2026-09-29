"""
Messaging abstraction.

Today (no broker, hardware not attached yet): everything runs through an
in-process Bus that mimics MQTT topic semantics (wildcard-free, exact-match
pub/sub). The mock generator and the FastAPI app both talk to this Bus, so
the whole system runs offline with zero setup.

Later (real ESP32s): flip app.config.MQTT_BROKER_URL to a real broker URL.
MqttBus below wraps paho-mqtt with the identical publish/subscribe interface,
so nothing else in the codebase has to change.
"""
from __future__ import annotations
import asyncio
import json
from collections import defaultdict
from typing import Awaitable, Callable

Handler = Callable[[str, dict], Awaitable[None] | None]


class Bus:
    """Simple async in-memory pub/sub. Topic match is exact string equality,
    same as the concrete topics we actually use (vtb/tank/{id}/telemetry etc)."""

    def __init__(self):
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler):
        self._subscribers[topic].append(handler)

    async def publish(self, topic: str, payload: dict):
        for handler in self._subscribers.get(topic, []):
            result = handler(topic, payload)
            if asyncio.iscoroutine(result):
                await result


class MqttBus:
    """Drop-in replacement for Bus, backed by a real MQTT broker via paho-mqtt.
    Same subscribe(topic, handler) / publish(topic, payload) interface.
    Swap this in once app.config.MQTT_BROKER_URL points at a real broker."""

    def __init__(self, broker_url: str, loop: asyncio.AbstractEventLoop):
        import paho.mqtt.client as mqtt
        from urllib.parse import urlparse

        self._loop = loop
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        parsed = urlparse(broker_url)
        self._client = mqtt.Client()
        self._client.on_message = self._on_message
        self._client.connect(parsed.hostname or "localhost", parsed.port or 1883)
        self._client.loop_start()

    def subscribe(self, topic: str, handler: Handler):
        self._handlers[topic].append(handler)
        self._client.subscribe(topic)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            return
        for handler in self._handlers.get(msg.topic, []):
            asyncio.run_coroutine_threadsafe(
                handler(msg.topic, payload) if asyncio.iscoroutinefunction(handler)
                else asyncio.coroutine(lambda: handler(msg.topic, payload))(),
                self._loop,
            )

    async def publish(self, topic: str, payload: dict):
        self._client.publish(topic, json.dumps(payload))


# Single shared bus instance used across the app + mock generator.
bus = Bus()
