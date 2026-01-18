#!/usr/bin/env python3
"""
Cortex Auto-Capture Hook for Claude Code

This script is triggered by Claude Code's SessionEnd hook when a session ends.
It analyzes the session transcript, determines significance, generates a summary
using an LLM, and saves the session to Cortex memory.

Input (stdin JSON):
{
    "session_id": "uuid",
    "transcript_path": "~/.claude/projects/.../session.jsonl",
    "cwd": "/project/path",
    "reason": "exit"
}

Exit codes:
  0 - Success (captured or skipped gracefully)
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

            # Extract project path
            if "project" in entry and not result["project_path"]:
                result["project_path"] = entry["project"]

            # Count tokens from content
            content = entry.get("display", entry.get("content", ""))
            if content:
                result["token_count"] += len(content) // 4
                text_parts.append(content)

            # Track tool calls and file edits
            entry_type = entry.get("type", "")

            if entry_type == "assistant" and "toolUse" in entry:
                for tu in entry.get("toolUse", []):
                    tool_name = tu.get("name", "")
                    tool_input = tu.get("input", {})

                    result["tool_calls"].append({
                        "name": tool_name,
                        "input": tool_input,
                    })

                    # Track file edits
                    if tool_name in ("Write", "Edit", "NotebookEdit"):
                        file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
                        if file_path:
                            result["files_edited"].add(file_path)

            elif entry_type == "tool_use":
                tool_name = entry.get("name", "")
                tool_input = entry.get("input", {})

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


def generate_summary(transcript_text: str, config: dict) -> str:
    """
    Generate a session summary using available LLM.

    Tries providers in order: Claude CLI, Anthropic API, Ollama
    """
    # Truncate transcript for context window
    max_chars = 80000
    if len(transcript_text) > max_chars:
        transcript_text = transcript_text[:max_chars] + "\n\n[... truncated ...]"

    prompt = f"""Analyze this Claude Code session transcript and write a detailed summary.

Focus on:
1. What was implemented or changed and WHY
2. Key architectural decisions made
3. Problems encountered and how they were solved
4. Non-obvious patterns or gotchas discovered
5. Future work or TODOs identified

Keep the summary comprehensive but concise (2-4 paragraphs).

Session Transcript:
---
{transcript_text}
---

Summary:"""

    # Try Claude CLI first (simplest, uses existing auth)
    import subprocess
    import shutil

    claude_path = shutil.which("claude")
    if claude_path:
        try:
            result = subprocess.run(
                [claude_path, "-p", prompt, "--model", "haiku"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            log(f"Claude CLI failed: {e}", "WARNING")

    # Try Anthropic API
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            payload = {
                "model": "claude-3-haiku-20240307",
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt}],
            }
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
                return data["content"][0]["text"]
        except Exception as e:
            log(f"Anthropic API failed: {e}", "WARNING")

    # Try Ollama
    ollama_url = config.get("llm", {}).get("ollama", {}).get("base_url", "http://localhost:11434")
    try:
        payload = {
            "model": config.get("llm", {}).get("ollama", {}).get("model", "llama3.2"),
            "prompt": prompt,
            "stream": False,
        }
        req = urllib.request.Request(
            f"{ollama_url}/api/generate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
            return data.get("response", "")
    except Exception as e:
        log(f"Ollama failed: {e}", "DEBUG")

    # Fallback: simple extraction
    return f"Session with {len(transcript_text)} characters of conversation."


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


def call_cortex_api(summary: str, changed_files: list, repository: str) -> bool:
    """
    Call the Cortex API to save the session.

    Returns True if successful.
    """
    try:
        payload = {
            "summary": summary,
            "changed_files": changed_files,
            "repository": repository,
        }

        req = urllib.request.Request(
            f"{CORTEX_API_URL}/api/commit",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                return True

    except urllib.error.URLError as e:
        log(f"Cortex API not available: {e}", "WARNING")
    except Exception as e:
        log(f"Cortex API call failed: {e}", "ERROR")

    return False


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

    # Generate summary
    summary = generate_summary(transcript["text"], config)
    log(f"Generated summary ({len(summary)} chars)")

    # Detect repository
    repository = detect_repository(transcript["project_path"] or cwd)

    # Get changed files
    changed_files = transcript["files_edited"]

    # Try to save via Cortex API
    if call_cortex_api(summary, changed_files, repository):
        log(f"Session saved to Cortex: {repository}")
        mark_session_captured(session_id)
        return 0

    # API not available - save to pending file for later
    pending_file = CORTEX_DATA_DIR / "pending_sessions.json"
    try:
        pending = []
        if pending_file.exists():
            pending = json.loads(pending_file.read_text())

        pending.append({
            "session_id": session_id,
            "summary": summary,
            "changed_files": changed_files,
            "repository": repository,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Keep only last 50 pending
        pending = pending[-50:]
        pending_file.write_text(json.dumps(pending, indent=2))

        log(f"Session queued for later (Cortex API unavailable)")
        mark_session_captured(session_id)

    except Exception as e:
        log(f"Failed to queue session: {e}", "ERROR")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Log error but exit cleanly
        log(f"Hook failed: {e}", "ERROR")
        sys.exit(0)
