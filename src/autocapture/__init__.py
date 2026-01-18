"""
Auto-Capture Module

Provides automatic session capture functionality for Claude Code sessions.
Includes transcript parsing, significance detection, and session summarization.
"""

from .transcript import (
    ParsedTranscript,
    Message,
    ToolCall,
    parse_transcript_file,
    parse_transcript_jsonl,
)
from .significance import (
    SignificanceResult,
    SignificanceConfig,
    calculate_significance,
    is_significant,
)
from .queue_processor import (
    QueueProcessor,
    get_processor,
    start_processor,
    stop_processor,
    trigger_processing,
)

__all__ = [
    # Transcript parsing
    "ParsedTranscript",
    "Message",
    "ToolCall",
    "parse_transcript_file",
    "parse_transcript_jsonl",
    # Significance detection
    "SignificanceResult",
    "SignificanceConfig",
    "calculate_significance",
    "is_significant",
    # Queue processing
    "QueueProcessor",
    "get_processor",
    "start_processor",
    "stop_processor",
    "trigger_processing",
]
