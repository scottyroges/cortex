#!/usr/bin/env python3
"""
CLI output formatting helpers for Cortex.

Usage:
    echo '<json>' | python3 cli_helpers.py format-status
    echo '<json>' | python3 cli_helpers.py format-initiatives
    echo '<json>' | python3 cli_helpers.py format-backups
    echo '<json>' | python3 cli_helpers.py format-search
    python3 cli_helpers.py url-encode <query>
"""

import json
import sys
import urllib.parse


def format_status(data: dict) -> None:
    """Format orient_session response for CLI display."""
    repo = data.get("repository", "unknown")
    branch = data.get("branch", "unknown")
    indexed = data.get("indexed", False)
    needs_reindex = data.get("needs_reindex", False)
    file_count = data.get("skeleton", {}).get("total_files", 0)

    print(f"Repository: {repo} ({branch})")
    print(f"Indexed: {'yes' if indexed else 'no'} ({file_count} files)")

    if needs_reindex:
        reason = data.get("reindex_reason", "unknown")
        print(f"  Needs reindex: {reason}")

    # Active initiative
    focused = data.get("focused_initiative")
    if focused:
        name = focused.get("name", "unknown")
        goal = focused.get("goal", "")
        print(f"\nActive Initiative: {name}")
        if goal:
            print(f"  Goal: {goal[:80]}{'...' if len(goal) > 80 else ''}")

    # Recent work
    recent = data.get("recent_work", [])
    if recent:
        print(f"\nRecent Work ({len(recent)} items):")
        for item in recent[:3]:
            # Truncate to first line
            first_line = item.split("\n")[0][:60]
            print(f"  - {first_line}...")

    # LLM status
    llm = data.get("llm_provider", "none")
    llm_ok = data.get("llm_available", False)
    print(f"\nLLM Provider: {llm} ({'available' if llm_ok else 'unavailable'})")


def format_initiatives(data: list | dict) -> None:
    """Format initiative list for CLI display."""
    # Handle both list and dict with 'initiatives' key
    if isinstance(data, dict):
        initiatives = data.get("initiatives", [])
    else:
        initiatives = data

    if not initiatives:
        print("No initiatives found.")
        return

    print(f"Initiatives ({len(initiatives)}):\n")
    for init in initiatives:
        name = init.get("name", "unnamed")
        status = init.get("status", "unknown")
        goal = init.get("goal", "")

        status_icon = "●" if status == "active" else "○"
        print(f"  {status_icon} {name}")
        if goal:
            print(f"    {goal[:70]}{'...' if len(goal) > 70 else ''}")


def format_backups(data: list | dict) -> None:
    """Format backup list for CLI display."""
    # Handle both list and dict with 'backups' key
    if isinstance(data, dict):
        backups = data.get("backups", [])
    else:
        backups = data

    if not backups:
        print("No backups found.")
        return

    print(f"Backups ({len(backups)}):\n")
    for backup in backups:
        path = backup.get("path", backup.get("backup_path", "unknown"))
        created = backup.get("created_at", backup.get("timestamp", "unknown"))
        label = backup.get("label", "")

        # Extract filename from path
        filename = path.split("/")[-1] if "/" in path else path
        print(f"  {filename}")
        if label:
            print(f"    Label: {label}")
        print(f"    Created: {created}")
        print()


def format_search(data: dict) -> None:
    """Format search results for CLI display."""
    query = data.get("query", "")
    results = data.get("results", [])
    timing = data.get("timing_ms", 0)

    print(f'Search: "{query}" ({len(results)} results, {timing}ms)\n')

    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results, 1):
        meta = r.get("metadata", {})
        score = r.get("score", 0)
        content = r.get("content", "")[:200]

        # Format source
        source = meta.get(
            "file_path", meta.get("url", meta.get("project", "unknown"))
        )
        doc_type = meta.get("type", "unknown")

        print(f"{i}. [{doc_type}] {source}")
        print(f"   Score: {score:.3f}")
        print(f"   {content}...")
        print()


def format_version_check(data: dict) -> None:
    """Format version check response for CLI display."""
    current = data.get("current_version", "unknown")
    latest = data.get("latest_version", "unknown")
    method = data.get("check_method", "none")
    update_available = data.get("update_available", False)

    if update_available:
        print(f"YES - {latest} available (current: {current})")
        print('  Run "cortex update" to update')
    elif method == "none":
        print("UNKNOWN (check failed)")
    else:
        print(f"NO (v{current} is latest)")


def url_encode(query: str) -> str:
    """URL-encode a query string."""
    return urllib.parse.quote(query)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: cli_helpers.py <command> [args]", file=sys.stderr)
        print("Commands: format-status, format-initiatives, format-backups, format-search, format-version-check, url-encode", file=sys.stderr)
        return 1

    command = sys.argv[1]

    if command == "url-encode":
        if len(sys.argv) < 3:
            print("Usage: cli_helpers.py url-encode <query>", file=sys.stderr)
            return 1
        print(url_encode(" ".join(sys.argv[2:])))
        return 0

    # All other commands read JSON from stdin
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input: {e}", file=sys.stderr)
        return 1

    if command == "format-status":
        format_status(data)
    elif command == "format-initiatives":
        format_initiatives(data)
    elif command == "format-backups":
        format_backups(data)
    elif command == "format-search":
        format_search(data)
    elif command == "format-version-check":
        format_version_check(data)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
