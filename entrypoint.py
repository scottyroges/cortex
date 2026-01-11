#!/usr/bin/env python3
"""
Cortex Container Entrypoint

Dispatches to the appropriate mode based on command line argument.

Modes:
  daemon  - Run HTTP server for MCP requests (default)
  bridge  - Run stdio-to-HTTP bridge for Claude Code session
  stdio   - Run original stdio MCP server (backward compatibility)
"""

import sys


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "daemon"

    if mode == "daemon":
        # Run HTTP server as daemon
        from http_server import run_server
        # Use port 8000 for MCP daemon (8080 reserved for debug/phase2)
        run_server(host="0.0.0.0", port=8000)

    elif mode == "bridge":
        # Run stdio-to-HTTP bridge
        from mcp_bridge import main as bridge_main
        bridge_main()

    elif mode == "stdio":
        # Original stdio MCP server (backward compatibility)
        from server import mcp
        mcp.run()

    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        print("Usage: entrypoint.py [daemon|bridge|stdio]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
