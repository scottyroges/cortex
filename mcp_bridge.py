#!/usr/bin/env python3
"""
MCP Stdio-to-HTTP Bridge

Reads MCP JSON-RPC messages from stdin, forwards to the Cortex HTTP daemon,
and writes responses to stdout.

This allows multiple Claude Code sessions to share a single Cortex daemon.
"""

import json
import os
import sys
import time

import requests

from logging_config import get_logger, setup_logging

setup_logging()
logger = get_logger("bridge")

# Configuration
DAEMON_URL = os.environ.get("CORTEX_DAEMON_URL", "http://localhost:8000")
REQUEST_TIMEOUT = int(os.environ.get("CORTEX_REQUEST_TIMEOUT", "300"))  # 5 min for ingestion


def send_response(response: dict) -> None:
    """Write JSON-RPC response to stdout."""
    print(json.dumps(response), flush=True)


def send_error(request_id, code: int, message: str) -> None:
    """Send a JSON-RPC error response."""
    send_response({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    })


def handle_initialize(request: dict) -> dict:
    """Handle MCP initialize request."""
    return {
        "jsonrpc": "2.0",
        "id": request.get("id"),
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": "cortex",
                "version": "1.0.0",
            },
        },
    }


def handle_tools_list(request: dict) -> dict:
    """Handle MCP tools/list request."""
    try:
        response = requests.get(
            f"{DAEMON_URL}/mcp/tools/list",
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()

        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": result,
        }
    except requests.RequestException as e:
        logger.error(f"Failed to list tools: {e}")
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {"code": -32000, "message": f"Daemon connection failed: {e}"},
        }


def handle_tools_call(request: dict) -> dict:
    """Handle MCP tools/call request."""
    params = request.get("params", {})
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    logger.info(f"Calling tool: {tool_name}")

    try:
        response = requests.post(
            f"{DAEMON_URL}/mcp/tools/call",
            json={"name": tool_name, "arguments": arguments},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()

        # Format as MCP tool result
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": result.get("content", ""),
                    }
                ],
                "isError": result.get("isError", False),
            },
        }
    except requests.Timeout:
        logger.error(f"Tool call timed out: {tool_name}")
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {"code": -32000, "message": f"Tool call timed out after {REQUEST_TIMEOUT}s"},
        }
    except requests.RequestException as e:
        logger.error(f"Tool call failed: {e}")
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {"code": -32000, "message": f"Daemon connection failed: {e}"},
        }


def handle_notification(request: dict) -> None:
    """Handle MCP notifications (no response needed)."""
    method = request.get("method", "")
    logger.debug(f"Received notification: {method}")
    # Notifications don't require a response


def wait_for_daemon(max_attempts: int = 30, delay: float = 0.5) -> bool:
    """Wait for daemon to become available."""
    logger.info(f"Waiting for daemon at {DAEMON_URL}...")

    for attempt in range(max_attempts):
        try:
            response = requests.get(f"{DAEMON_URL}/health", timeout=2)
            if response.status_code == 200:
                logger.info("Daemon is ready")
                return True
        except requests.RequestException:
            pass

        time.sleep(delay)

    logger.error("Daemon did not become available")
    return False


def main():
    """Main bridge loop."""
    logger.info(f"MCP Bridge starting, daemon URL: {DAEMON_URL}")

    # Wait for daemon to be ready
    if not wait_for_daemon():
        # Send error for any pending requests
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32000, "message": "Cortex daemon not available"},
        }), flush=True)
        sys.exit(1)

    # Process stdin line by line
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")
            send_error(None, -32700, f"Parse error: {e}")
            continue

        method = request.get("method", "")
        request_id = request.get("id")

        logger.debug(f"Received: {method} (id={request_id})")

        # Route by method
        if method == "initialize":
            response = handle_initialize(request)
            send_response(response)

        elif method == "notifications/initialized":
            handle_notification(request)
            # No response for notifications

        elif method == "tools/list":
            response = handle_tools_list(request)
            send_response(response)

        elif method == "tools/call":
            response = handle_tools_call(request)
            send_response(response)

        elif method.startswith("notifications/"):
            handle_notification(request)
            # No response for notifications

        else:
            logger.warning(f"Unknown method: {method}")
            if request_id is not None:
                send_error(request_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bridge interrupted")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Bridge error: {e}")
        sys.exit(1)
