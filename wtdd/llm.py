"""The one model call path for the whole package: OpenRouter, OpenAI-compatible chat completions, Claude models.

  text:    generate("central", [{"role": "user", "content": "..."}])       -> {"text", "model", "usage", "finish_reason", "raw"}
  tools:   generate(..., tools=[function specs])  and read raw["choices"][0]["message"]["tool_calls"] (wtdd/agent.py)
  images:  put {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<b64>"}} parts in a message's content
           list; a call with image parts uses OPENROUTER_VISION_MODEL, otherwise OPENROUTER_MODEL (model_id overrides both)
  JSON:    response_format={"type": "json_object"} (or a json_schema); validate the result yourself
Every call is one ledger row (tool llm.generate, agent as given) with model, message and image counts, tokens, latency.
No retries and no fallback model (CLAUDE.md section 2): a non-200, or a finish_reason other than stop/end_turn/length/
tool_calls, is recorded on this step and raised. Env: OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_VISION_MODEL.
"""
from __future__ import annotations
import json
from typing import Any

import requests

from . import config
from .ledger import step

URL = "https://openrouter.ai/api/v1/chat/completions"


def generate(agent: str, messages: list[dict[str, Any]], *, model_id: str | None = None,
             max_tokens: int = 400, temperature: float = 0.4, response_format: dict | None = None,
             timeout: float = 60.0, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    n_img = sum(1 for m in messages if isinstance(m.get("content"), list)
                for p in m["content"] if p.get("type") == "image_url")
    mid = model_id or config.get("OPENROUTER_VISION_MODEL" if n_img else "OPENROUTER_MODEL")
    body: dict[str, Any] = {"model": mid, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if response_format:
        body["response_format"] = response_format
    if tools:
        body["tools"] = tools
    headers = {"Authorization": f"Bearer {config.get('OPENROUTER_API_KEY')}",
               "HTTP-Referer": "https://github.com/Jshengdev/what-the-dog-doin",
               "X-Title": "what-the-dog-doin", "Content-Type": "application/json"}
    with step(agent, "llm.generate", "openrouter",
              {"model": mid, "n_messages": len(messages), "n_images": n_img, "max_tokens": max_tokens}) as r:
        resp = requests.post(URL, headers=headers, data=json.dumps(body), timeout=timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"openrouter {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        finish = choice.get("finish_reason")
        if finish not in ("stop", "end_turn", "length", "tool_calls", None):
            raise RuntimeError(f"openrouter finish_reason={finish}: {text[:200]}")
        out = {"text": text, "model": data.get("model", mid), "usage": data.get("usage", {}), "finish_reason": finish, "raw": data}
        r["state_after"] = {"model": out["model"], "usage": out["usage"], "finish": finish, "chars": len(text),
                            "tool_calls": [t["function"]["name"] for t in (choice["message"].get("tool_calls") or [])]}
        r["response_or_error"] = text[:600]
        return out
