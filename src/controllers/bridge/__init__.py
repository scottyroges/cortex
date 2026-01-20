"""
MCP Stdio-to-HTTP Bridge

Reads MCP JSON-RPC messages from stdin, forwards to the Cortex HTTP daemon,
and writes responses to stdout. This allows multiple Claude Code sessions
to share a single Cortex daemon.
"""

from src.controllers.bridge.bridge import main

__all__ = ["main"]
