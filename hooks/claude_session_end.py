#!/usr/bin/env python3
"""
Cortex Auto-Capture Hook for Claude Code

This script is triggered by Claude Code's SessionEnd hook when a session ends.
It analyzes the session transcript, determines significance, and queues the
session for async processing by the Cortex daemon.

The hook is designed to exit FAST (<100ms) to avoid blocking Claude Code exit.
Summary generation and storage happen asynchronously in the daemon.

Flow:
  1. Parse transcript (fast - just file read)
  2. Check significance (fast - just counting)
  3. Queue for processing (fast - just file write)
  4. Ping daemon to wake up (fire-and-forget)
  5. EXIT IMMEDIATELY

Input (stdin JSON):
{
    "session_id": "uuid",
    "transcript_path": "~/.claude/projects/.../session.jsonl",
    "cwd": "/project/path",
    "reason": "exit"
}

Exit codes:
  0 - Success (queued or skipped gracefully)
  1 - Error (logged but non-fatal to Claude Code)
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


# Configuration
CORTEX_API_URL = os.environ.get("CORTEX_API_URL", "http://localhost:8080")
CORTEX_DATA_DIR = Path.home() / ".cortex"
CAPTURED_SESSIONS_FILE = CORTEX_DATA_DIR / "captured_sessions.json"
HOOK_LOG_FILE = CORTEX_DATA_DIR / "hook.log"

# Default significance thresholds
DEFAULT_MIN_TOKENS = 5000
DEFAULT_MIN_FILE_EDITS = 1
DEFAULT_MIN_TOOL_CALLS = 3


def log(message: str, level: str = "INFO"):
    """Log a message to the hook log file."""
    try:
        CORTEX_DATA_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        with open(HOOK_LOG_FILE, "a") as f:
            f.write(f"{timestamp} [{level}] {message}\n")
    except Exception:
        pass  # Logging failures shouldn't break the hook


def load_config() -> dict:
    """Load Cortex configuration."""
    config_path = CORTEX_DATA_DIR / "config.yaml"
    if not config_path.exists():
        return {}

    try:
        import yaml
        return yaml.safe_load(config_path.read_text()) or {}
    except ImportError:
        # Fallback: try to parse simple YAML manually
        return {}
    except Exception as e:
        log(f"Failed to load config: {e}", "WARNING")
        return {}


def is_session_captured(session_id: str) -> bool:
    """Check if a session has already been captured."""
    if not CAPTURED_SESSIONS_FILE.exists():
        return False

    try:
        data = json.loads(CAPTURED_SESSIONS_FILE.read_text())
        return session_id in data.get("captured", [])
    except Exception:
        return False


def mark_session_captured(session_id: str):
    """Mark a session as captured to prevent re-capture."""
    try:
        CORTEX_DATA_DIR.mkdir(parents=True, exist_ok=True)

        data = {"captured": []}
        if CAPTURED_SESSIONS_FILE.exists():
            try:
                data = json.loads(CAPTURED_SESSIONS_FILE.read_text())
            except Exception:
                pass

        if session_id not in data.get("captured", []):
            data.setdefault("captured", []).append(session_id)
            # Keep only last 1000 sessions
            data["captured"] = data["captured"][-1000:]

        CAPTURED_SESSIONS_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        log(f"Failed to mark session captured: {e}", "WARNING")


def parse_transcript(transcript_path: str) -> dict:
    """
    Parse a Claude Code transcript file.

    Returns dict with:
        - messages: list of messages
        - tool_calls: list of tool calls
        - files_edited: list of file paths
        - token_count: approximate token count
        - project_path: project directory
    """
    result = {
        "messages": [],
        "tool_calls": [],
        "files_edited": set(),
        "token_count": 0,
        "project_path": None,
        "text": "",
    }

    path = Path(transcript_path).expanduser()
    if not path.exists():
        log(f"Transcript file not found: {path}", "WARNING")
        return result

    text_parts = []

    try:
        for line in path.read_text().strip().split("\n"):
            if not line.strip():
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Extract project path from cwd field
            if "cwd" in entry and not result["project_path"]:
                result["project_path"] = entry["cwd"]

            # Get message content - Claude Code nests under "message"
            message = entry.get("message", {})
            role = message.get("role", entry.get("type", ""))
            content = message.get("content", entry.get("display", entry.get("content", "")))

            # Handle content that can be string or array of content blocks
            if isinstance(content, str) and content:
                result["token_count"] += len(content) // 4
                text_parts.append(f"[{role.upper()}] {content}")
                result["messages"].append({"role": role, "content": content})

            elif isinstance(content, list):
                # Array of content blocks (text, tool_use, tool_result, etc.)
                for block in content:
                    block_type = block.get("type", "")

                    if block_type == "text":
                        text = block.get("text", "")
                        if text:
                            result["token_count"] += len(text) // 4
                            text_parts.append(f"[{role.upper()}] {text}")
                            result["messages"].append({"role": role, "content": text})

                    elif block_type == "tool_use":
                        tool_name = block.get("name", "")
                        tool_input = block.get("input", {})

                        result["tool_calls"].append({
                            "name": tool_name,
                            "input": tool_input,
                        })

                        # Track file edits
                        if tool_name in ("Write", "Edit", "NotebookEdit"):
                            file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
                            if file_path:
                                result["files_edited"].add(file_path)

                    elif block_type == "tool_result":
                        # Tool results also count toward content
                        result_content = block.get("content", "")
                        if isinstance(result_content, str) and result_content:
                            result["token_count"] += len(result_content) // 4

            # Legacy format support: direct toolUse array
            if "toolUse" in entry:
                for tu in entry.get("toolUse", []):
                    tool_name = tu.get("name", "")
                    tool_input = tu.get("input", {})

                    result["tool_calls"].append({
                        "name": tool_name,
                        "input": tool_input,
                    })

                    if tool_name in ("Write", "Edit", "NotebookEdit"):
                        file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
                        if file_path:
                            result["files_edited"].add(file_path)

    except Exception as e:
        log(f"Error parsing transcript: {e}", "ERROR")

    result["files_edited"] = list(result["files_edited"])
    result["text"] = "\n\n".join(text_parts)

    return result


def is_significant(transcript: dict, config: dict) -> tuple[bool, str]:
    """
    Check if a session is significant enough to capture.

    Returns (is_significant, reason)
    """
    autocapture_config = config.get("autocapture", {}).get("significance", {})

    min_tokens = autocapture_config.get("min_tokens", DEFAULT_MIN_TOKENS)
    min_edits = autocapture_config.get("min_file_edits", DEFAULT_MIN_FILE_EDITS)
    min_tools = autocapture_config.get("min_tool_calls", DEFAULT_MIN_TOOL_CALLS)

    tokens = transcript["token_count"]
    edits = len(transcript["files_edited"])
    tools = len(transcript["tool_calls"])

    reasons = []

    if tokens >= min_tokens:
        reasons.append(f"{tokens} tokens")
    if edits >= min_edits:
        reasons.append(f"{edits} file edits")
    if tools >= min_tools:
        reasons.append(f"{tools} tool calls")

    if reasons:
        return True, ", ".join(reasons)

    return False, f"tokens={tokens}, edits={edits}, tools={tools}"


def queue_session_for_processing(
    session_id: str,
    transcript_text: str,
    files_edited: list,
    repository: str,
) -> bool:
    """
    Queue a session for async processing by the Cortex daemon.

    The daemon will generate the summary and save to Cortex asynchronously,
    allowing the hook to exit immediately.

    Returns True if queued successfully.
    """
    queue_file = CORTEX_DATA_DIR / "capture_queue.json"

    try:
        CORTEX_DATA_DIR.mkdir(parents=True, exist_ok=True)

        queue = []
        if queue_file.exists():
            try:
                queue = json.loads(queue_file.read_text())
            except Exception:
                queue = []

        # Add session to queue
        queue.append({
            "session_id": session_id,
            "transcript_text": transcript_text,
            "files_edited": files_edited,
            "repository": repository,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })

        # Keep only last 100 queued sessions
        queue = queue[-100:]
        queue_file.write_text(json.dumps(queue, indent=2))

        return True

    except Exception as e:
        log(f"Failed to queue session: {e}", "ERROR")
        return False


def notify_daemon():
    """
    Notify the Cortex daemon that there are sessions to process.

    This is a fire-and-forget ping - if daemon isn't running, the queue
    will be processed when it starts.
    """
    try:
        req = urllib.request.Request(
            f"{CORTEX_API_URL}/api/process-queue",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        # Very short timeout - we don't care about the response
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        # Daemon not running or slow - that's fine, queue will be processed later
        pass


def detect_repository(project_path: str) -> str:
    """Detect repository name from project path."""
    if not project_path:
        return "global"

    path = Path(project_path)

    # Try to get git repo name
    try:
        import subprocess
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).name
    except Exception:
        pass

    return path.name


def main():
    """Main hook entry point."""
    try:
        # Read input from stdin
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        log(f"Invalid input JSON: {e}", "ERROR")
        return 0  # Exit cleanly to not break Claude Code

    session_id = input_data.get("session_id", "unknown")
    transcript_path = input_data.get("transcript_path", "")
    cwd = input_data.get("cwd", "")
    reason = input_data.get("reason", "")

    log(f"SessionEnd hook triggered: session={session_id}, reason={reason}")

    # Check if already captured
    if is_session_captured(session_id):
        log(f"Session {session_id} already captured, skipping")
        return 0

    # Load config
    config = load_config()

    # Check if autocapture is enabled
    if not config.get("autocapture", {}).get("enabled", True):
        log("Auto-capture disabled in config")
        return 0

    # Parse transcript
    transcript = parse_transcript(transcript_path)

    if not transcript["messages"] and not transcript["tool_calls"]:
        log("Empty transcript, skipping")
        return 0

    # Check significance
    significant, sig_reason = is_significant(transcript, config)

    if not significant:
        log(f"Session not significant: {sig_reason}")
        return 0

    log(f"Session is significant: {sig_reason}")

    # Detect repository
    repository = detect_repository(transcript["project_path"] or cwd)

    # Queue session for async processing (fast - no LLM call)
    if queue_session_for_processing(
        session_id=session_id,
        transcript_text=transcript["text"],
        files_edited=transcript["files_edited"],
        repository=repository,
    ):
        log(f"Session queued for async processing: {repository}")
        mark_session_captured(session_id)

        # Notify daemon to process queue (fire-and-forget)
        notify_daemon()
    else:
        log("Failed to queue session", "ERROR")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Log error but exit cleanly
        log(f"Hook failed: {e}", "ERROR")
        sys.exit(0)
