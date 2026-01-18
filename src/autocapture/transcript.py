"""
Transcript Parsing

Parse Claude Code session transcripts from JSONL format.
Extracts messages, tool calls, and metadata for analysis.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from logging_config import get_logger

logger = get_logger("autocapture.transcript")


@dataclass
class ToolCall:
    """Represents a single tool call in the session."""

    name: str
    input: dict[str, Any]
    output: Optional[str] = None
    success: bool = True
    timestamp: Optional[datetime] = None

    @property
    def is_file_edit(self) -> bool:
        """Check if this tool call modified a file."""
        return self.name in ("Write", "Edit", "NotebookEdit")

    @property
    def edited_file(self) -> Optional[str]:
        """Get the file path if this was a file edit, None otherwise."""
        if not self.is_file_edit:
            return None
        # Both Write and Edit use file_path parameter
        return self.input.get("file_path") or self.input.get("notebook_path")


@dataclass
class Message:
    """Represents a message in the session transcript."""

    role: str  # "user", "assistant", "system"
    content: str
    timestamp: Optional[datetime] = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def approximate_tokens(self) -> int:
        """Rough token count estimate (chars / 4)."""
        return len(self.content) // 4


@dataclass
class ParsedTranscript:
    """Parsed session transcript with extracted data."""

    session_id: str
    project_path: Optional[str]
    messages: list[Message]
    tool_calls: list[ToolCall]
    start_time: Optional[datetime]
    end_time: Optional[datetime]

    @property
    def token_count(self) -> int:
        """Approximate total token count."""
        return sum(m.approximate_tokens for m in self.messages)

    @property
    def files_edited(self) -> list[str]:
        """List of unique file paths that were edited."""
        files = set()
        for tc in self.tool_calls:
            if tc.edited_file:
                files.add(tc.edited_file)
        return sorted(files)

    @property
    def duration_seconds(self) -> int:
        """Session duration in seconds, or 0 if unknown."""
        if self.start_time and self.end_time:
            return int((self.end_time - self.start_time).total_seconds())
        return 0

    @property
    def tool_call_count(self) -> int:
        """Total number of tool calls."""
        return len(self.tool_calls)

    def to_text(self, max_chars: Optional[int] = None) -> str:
        """
        Convert transcript to plain text for summarization.

        Args:
            max_chars: Maximum characters to include (None for unlimited)

        Returns:
            Plain text representation of the transcript
        """
        lines = []

        for msg in self.messages:
            role = msg.role.upper()
            lines.append(f"[{role}]")
            lines.append(msg.content)

            # Include tool calls inline
            for tc in msg.tool_calls:
                lines.append(f"\n[TOOL: {tc.name}]")
                if tc.output:
                    # Truncate long outputs
                    output = tc.output[:500] if len(tc.output) > 500 else tc.output
                    lines.append(f"Output: {output}")
            lines.append("")

        text = "\n".join(lines)

        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "\n\n[... transcript truncated ...]"

        return text


def parse_transcript_file(file_path: str | Path) -> ParsedTranscript:
    """
    Parse a transcript from a JSONL file.

    Args:
        file_path: Path to the JSONL transcript file

    Returns:
        ParsedTranscript with extracted data

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is invalid
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Transcript file not found: {file_path}")

    content = file_path.read_text(encoding="utf-8")
    session_id = file_path.stem  # Use filename as session ID

    return parse_transcript_jsonl(content, session_id)


def parse_transcript_jsonl(content: str, session_id: str = "unknown") -> ParsedTranscript:
    """
    Parse a transcript from JSONL content.

    Claude Code transcripts are JSONL files where each line is a JSON object
    representing an event in the session.

    Args:
        content: JSONL content string
        session_id: Session identifier

    Returns:
        ParsedTranscript with extracted data
    """
    messages: list[Message] = []
    tool_calls: list[ToolCall] = []
    project_path: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    for line_num, line in enumerate(content.strip().split("\n"), 1):
        line = line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON on line {line_num}: {e}")
            continue

        # Extract timestamp
        timestamp = None
        if "timestamp" in entry:
            try:
                # Claude Code uses millisecond timestamps
                ts = entry["timestamp"]
                if isinstance(ts, (int, float)):
                    timestamp = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            except (ValueError, TypeError):
                pass

        # Track session time bounds
        if timestamp:
            if start_time is None or timestamp < start_time:
                start_time = timestamp
            if end_time is None or timestamp > end_time:
                end_time = timestamp

        # Extract project path from cwd field (current format) or project (legacy)
        if "cwd" in entry and project_path is None:
            project_path = entry["cwd"]
        elif "project" in entry and project_path is None:
            project_path = entry["project"]

        # Claude Code nests message content under "message" key
        message = entry.get("message", {})
        role = message.get("role", entry.get("type", ""))
        content = message.get("content", entry.get("display", entry.get("content", "")))

        # Handle content that can be string or array of content blocks
        if isinstance(content, str) and content:
            messages.append(
                Message(
                    role=role,
                    content=content,
                    timestamp=timestamp,
                )
            )

        elif isinstance(content, list):
            # Array of content blocks (text, tool_use, tool_result, thinking, etc.)
            msg_tool_calls = []
            text_parts = []

            for block in content:
                block_type = block.get("type", "")

                if block_type == "text":
                    text = block.get("text", "")
                    if text:
                        text_parts.append(text)

                elif block_type == "tool_use":
                    tc = ToolCall(
                        name=block.get("name", "unknown"),
                        input=block.get("input", {}),
                        timestamp=timestamp,
                    )
                    tool_calls.append(tc)
                    msg_tool_calls.append(tc)

                elif block_type == "tool_result":
                    # Tool result in content array - find matching tool call
                    tool_use_id = block.get("tool_use_id", "")
                    result_content = block.get("content", "")
                    if isinstance(result_content, list):
                        # Content can be array of text blocks
                        result_content = " ".join(
                            b.get("text", "") for b in result_content if b.get("type") == "text"
                        )

            # Create message if we have text or tool calls
            combined_text = "\n".join(text_parts)
            if combined_text or msg_tool_calls:
                messages.append(
                    Message(
                        role=role,
                        content=combined_text,
                        timestamp=timestamp,
                        tool_calls=msg_tool_calls,
                    )
                )

        # Legacy format support: direct toolUse array at entry level
        if "toolUse" in entry:
            for tu in entry.get("toolUse", []):
                tc = ToolCall(
                    name=tu.get("name", "unknown"),
                    input=tu.get("input", {}),
                    timestamp=timestamp,
                )
                tool_calls.append(tc)

    return ParsedTranscript(
        session_id=session_id,
        project_path=project_path,
        messages=messages,
        tool_calls=tool_calls,
        start_time=start_time,
        end_time=end_time,
    )


def extract_changed_files(transcript: ParsedTranscript) -> list[str]:
    """
    Extract list of files that were modified in the session.

    Args:
        transcript: Parsed transcript

    Returns:
        List of file paths that were edited
    """
    return transcript.files_edited
