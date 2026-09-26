"""The tool registry: one file in this folder is one tool, named after the file. A tool module is its docstring (the
doc), an ARGS spec, and run(**kwargs) that does the real thing, reads the result back, and returns a JSON-able dict
(or raises; nothing here returns a canned result).

  ARGS = {"percent": {"type": "number", "default": 20, "doc": "0 to 100"}}      types: string, number, boolean
  def run(percent=20): ...
Imports that pull in a device SDK belong inside run(), so listing the tools stays cheap. Every caller shares this
registry, so every action has one code path: the CLI (python -m wtdd <tool> k=v), the HTTP API (python -m wtdd.api,
POST /tools/<name>), the MCP server (python -m wtdd.mcp_server), the chat commands (wtdd/commands.py HANDLERS), the
chat wake demo (dog_on_fire, walk_path) and the model loop (wtdd/agent.py). call() rejects unknown args, fills ARGS
defaults and coerces a boolean arg given as a string ("1", "true", "on", "yes"), so a JSON body, a CLI key=value and
a model's function call all behave the same. The 23 tools: chat_post, dog_cmd, dog_look, dog_on_fire, dog_round, dog_say,
hue_light_set, hue_signal, identify, intruder_alarm, ledger_tail, light_alarm, light_show, lights_dim, lights_off, lights_on, lights_status,
plan_path, strip_fade, strip_set, strip_temp, walk_path, zone_set. Tool names are an HTTP and MCP contract (ui/index.html).
"""
from __future__ import annotations
import importlib
import pkgutil
from typing import Any

TRUE = ("1", "true", "on", "yes")


def registry() -> dict[str, Any]:
    mods = {m.name: importlib.import_module(f"{__name__}.{m.name}") for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_")}
    return {n: m for n, m in sorted(mods.items()) if hasattr(m, "run")}


def describe() -> list[dict[str, Any]]:
    return [{"name": n, "doc": (m.__doc__ or "").strip(), "args": getattr(m, "ARGS", {})} for n, m in registry().items()]


def call(tool: str, **kwargs: Any) -> Any:
    tools = registry()
    if tool not in tools:
        raise KeyError(f"no tool {tool!r}; tools: {', '.join(tools)}")
    spec = getattr(tools[tool], "ARGS", {})
    unknown = set(kwargs) - set(spec)
    if unknown:
        raise ValueError(f"{tool}: unknown args {sorted(unknown)}; accepts {sorted(spec)}")
    for k, v in spec.items():
        if k not in kwargs:
            if "default" in v:
                kwargs[k] = v["default"]
        elif v.get("type") == "boolean" and not isinstance(kwargs[k], bool):
            kwargs[k] = str(kwargs[k]).lower() in TRUE
    return tools[tool].run(**kwargs)
