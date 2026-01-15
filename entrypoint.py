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
        import os
        from src.http import run_server
        port = int(os.environ.get("CORTEX_HTTP_PORT", "8080"))
        run_server(host="0.0.0.0", port=port)

    elif mode == "bridge":
        # Run stdio-to-HTTP bridge
        from mcp_bridge import main as bridge_main
        bridge_main()

    elif mode == "stdio":
        # Original stdio MCP server (backward compatibility)
        from src.server import mcp
        mcp.run()

    elif mode == "browse":
        # Run TUI memory browser
        from src.browser.terminal import run_browser
        # Get daemon URL from environment or use default
        import os
        base_url = os.environ.get("CORTEX_HTTP_URL", "http://localhost:8080")
        run_browser(base_url=base_url)

    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        print("Usage: entrypoint.py [daemon|bridge|stdio|browse]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
