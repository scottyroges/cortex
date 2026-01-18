"""
Session Significance Detection

Determines whether a session is significant enough to capture automatically.
Uses configurable thresholds for tokens, file edits, and tool calls.
"""

from dataclasses import dataclass, field
from typing import Optional

from .transcript import ParsedTranscript
from logging_config import get_logger

logger = get_logger("autocapture.significance")


@dataclass
class SignificanceConfig:
    """Configuration for significance thresholds."""

    min_tokens: int = 5000
    """Minimum token count to consider significant."""

    min_file_edits: int = 1
    """Minimum number of file edits to consider significant."""

    min_tool_calls: int = 3
    """Minimum number of tool calls to consider significant."""

    require_all: bool = False
    """If True, ALL thresholds must be met. If False, ANY threshold triggers significance."""


@dataclass
class SignificanceResult:
    """Result of significance calculation."""

    is_significant: bool
    """Whether the session meets significance criteria."""

    token_count: int
    """Actual token count."""

    file_edit_count: int
    """Number of files edited."""

    tool_call_count: int
    """Number of tool calls."""

    reasons: list[str] = field(default_factory=list)
    """Reasons why the session is/isn't significant."""

    @property
    def summary(self) -> str:
        """Human-readable summary of significance."""
        if self.is_significant:
            return f"Significant: {', '.join(self.reasons)}"
        return f"Not significant: tokens={self.token_count}, edits={self.file_edit_count}, tools={self.tool_call_count}"


# Default significance config
DEFAULT_CONFIG = SignificanceConfig()


def calculate_significance(
    transcript: ParsedTranscript,
    config: Optional[SignificanceConfig] = None,
) -> SignificanceResult:
    """
    Calculate significance metrics for a session.

    Args:
        transcript: Parsed session transcript
        config: Significance thresholds (uses defaults if None)

    Returns:
        SignificanceResult with metrics and determination
    """
    config = config or DEFAULT_CONFIG

    token_count = transcript.token_count
    file_edit_count = len(transcript.files_edited)
    tool_call_count = transcript.tool_call_count

    # Check each threshold
    meets_tokens = token_count >= config.min_tokens
    meets_edits = file_edit_count >= config.min_file_edits
    meets_tools = tool_call_count >= config.min_tool_calls

    # Build reasons list
    reasons = []
    if meets_tokens:
        reasons.append(f"{token_count} tokens (>= {config.min_tokens})")
    if meets_edits:
        reasons.append(f"{file_edit_count} file edits (>= {config.min_file_edits})")
    if meets_tools:
        reasons.append(f"{tool_call_count} tool calls (>= {config.min_tool_calls})")

    # Determine overall significance
    if config.require_all:
        is_sig = meets_tokens and meets_edits and meets_tools
    else:
        is_sig = meets_tokens or meets_edits or meets_tools

    return SignificanceResult(
        is_significant=is_sig,
        token_count=token_count,
        file_edit_count=file_edit_count,
        tool_call_count=tool_call_count,
        reasons=reasons,
    )


def is_significant(
    transcript: ParsedTranscript,
    config: Optional[SignificanceConfig] = None,
) -> bool:
    """
    Quick check if a session is significant.

    Args:
        transcript: Parsed session transcript
        config: Significance thresholds

    Returns:
        True if session is significant
    """
    result = calculate_significance(transcript, config)
    return result.is_significant


def create_config_from_dict(config_dict: dict) -> SignificanceConfig:
    """
    Create SignificanceConfig from a dictionary.

    Args:
        config_dict: Dictionary with threshold values

    Returns:
        SignificanceConfig instance
    """
    return SignificanceConfig(
        min_tokens=config_dict.get("min_tokens", DEFAULT_CONFIG.min_tokens),
        min_file_edits=config_dict.get("min_file_edits", DEFAULT_CONFIG.min_file_edits),
        min_tool_calls=config_dict.get("min_tool_calls", DEFAULT_CONFIG.min_tool_calls),
        require_all=config_dict.get("require_all", DEFAULT_CONFIG.require_all),
    )
