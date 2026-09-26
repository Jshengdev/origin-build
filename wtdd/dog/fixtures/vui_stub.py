"""TEST ONLY. A recording stand-in for the driver's data channel, for wtdd/dog/test_led.py and the dry screenshot's scratch
ledger. Nothing here reaches a dog.

Body._request awaits conn.datachannel.pub_sub.publish_request_new(topic, options) and reads the status code at
data.header.status.code, so this records (topic, options) exactly as sent and answers per api_id in the driver's reply
shape: {type: "res", topic, data: {header: {identity: {id, api_id}, status: {code}}, data: <json string>}} (msgs/pub_sub.py
and webrtc_datachannel.py of unitree_webrtc_connect 2.2.0). An answer that is an exception is raised instead of a reply
(TimeoutError stands for a dog that never answers); an api_id with no planted answer raises KeyError, so a test that asks
for something it did not plant fails loud. A caller that writes rows through this stub labels them cached=True,
source="stub" (NIGHT-1 contracts E); the stub itself writes nothing.

  StubConn({1007: (0, None), 1006: (0, {"brightness": 7})}, delay={1007: 0.3})   answers and optional per-id delays (s)
  conn.sent                                                                        [(topic, options), ...] in send order
"""
from __future__ import annotations
import asyncio
import copy
import json
from types import SimpleNamespace
from typing import Any


def reply(topic: str, api_id: int, code: int, data: Any = None) -> dict:
    """One reply in the driver's shape; `data` is json-encoded into the inner string like the dog's own replies."""
    return {"type": "res", "topic": topic,
            "data": {"header": {"identity": {"id": 1, "api_id": api_id}, "status": {"code": code}},
                     "data": json.dumps(data) if data is not None else ""}}


class _PubSub:
    def __init__(self, answers: dict, delay: dict) -> None:
        self.answers, self.delay, self.sent = answers, delay, []

    async def publish_request_new(self, topic: str, options: dict) -> dict:
        self.sent.append((topic, copy.deepcopy(options)))
        api_id = options["api_id"]
        if api_id in self.delay:
            await asyncio.sleep(self.delay[api_id])
        if api_id not in self.answers:
            raise KeyError(f"vui_stub: no answer planted for api_id {api_id} on {topic}")
        a = self.answers[api_id]
        if isinstance(a, BaseException):
            raise a
        code, data = a
        return reply(topic, api_id, code, data)


class StubConn:
    """Stands where Body.conn stands: .datachannel.pub_sub.publish_request_new, and .sent for the assertions."""

    def __init__(self, answers: dict | None = None, delay: dict | None = None) -> None:
        self.datachannel = SimpleNamespace(pub_sub=_PubSub(dict(answers or {}), dict(delay or {})))

    @property
    def sent(self) -> list[tuple[str, dict]]:
        return self.datachannel.pub_sub.sent
