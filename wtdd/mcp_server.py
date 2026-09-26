"""MCP (stdio) server over the same tool registry, so any MCP client (Claude Code, Codex, Hermes) can drive the house.

  claude mcp add wtdd -- /abs/path/to/.venv/bin/python -m wtdd.mcp_server
  python -m wtdd.mcp_server        (stdio; nothing to see, the client speaks JSON-RPC to it)
Each file in wtdd/tools becomes one MCP tool with the same name and doc (the ARGS spec is appended to the description)
and a single parameter `args`: a JSON object string of the tool's arguments. Results are JSON strings; an error inside a
tool surfaces as the MCP tool error, never as a made-up result. Needs the mcp python SDK: 2.x (mcp.server.mcpserver,
2.2.0 verified) or 1.x (mcp.server.fastmcp.FastMCP, same add_tool(fn, name=, description=)); with neither installed
it prints the pip hint and exits 1. No other Python file imports this module.
"""
from __future__ import annotations
import json
import sys

from . import tools


def main() -> int:
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as MCPServer  # mcp 1.x name
        except ImportError:
            print("pip install mcp   (the MCP python SDK) then re-run", file=sys.stderr)
            return 1
    mcp = MCPServer("wtdd")

    def make(n):
        def tool(args: str = "{}") -> str:
            """args: JSON object of the tool's arguments."""
            return json.dumps(tools.call(n, **json.loads(args or "{}")), default=str)
        return tool
    for t in tools.describe():
        mcp.add_tool(make(t["name"]), name=t["name"], description=t["doc"] + (f"\nargs: {json.dumps(t['args'])}" if t["args"] else ""))
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
