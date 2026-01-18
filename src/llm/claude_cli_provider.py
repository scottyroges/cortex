"""
Claude CLI Provider

Uses the `claude` command-line tool for generation.
Inherits authentication from the CLI's own config.
"""

import subprocess
import shutil
import time
from typing import Optional

from .provider import LLMProvider, LLMConfig, LLMResponse
from logging_config import get_logger

logger = get_logger("llm.claude_cli")


class ClaudeCLIProvider(LLMProvider):
    """
    LLM provider using the Claude CLI.

    Configuration:
        model: Model flag to pass to CLI (default: haiku)

    Requires:
        `claude` CLI to be installed and authenticated
    """

    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}
        self._cli_path = None

    @property
    def name(self) -> str:
        return "claude-cli"

    @property
    def default_model(self) -> str:
        return self._config.get("model", "haiku")

    def is_available(self) -> bool:
        """Check if claude CLI is installed and accessible."""
        self._cli_path = shutil.which("claude")
        if self._cli_path is None:
            logger.debug("Claude CLI not found in PATH")
            return False

        # Quick check that it runs
        try:
            result = subprocess.run(
                [self._cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception as e:
            logger.debug(f"Claude CLI check failed: {e}")
            return False

    def generate(self, prompt: str, config: Optional[LLMConfig] = None) -> LLMResponse:
        """Generate completion using Claude CLI."""
        if self._cli_path is None:
            if not self.is_available():
                raise RuntimeError("Claude CLI not available")

        config = config or LLMConfig()
        model = config.model or self.default_model

        start_time = time.time()

        try:
            # Build command
            cmd = [
                self._cli_path,
                "-p",  # Print mode (no interactive)
                prompt,
                "--model",
                model,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=config.timeout,
            )

            latency_ms = (time.time() - start_time) * 1000

            if result.returncode != 0:
                error_msg = result.stderr.strip() or "Unknown error"
                raise RuntimeError(f"Claude CLI failed: {error_msg}")

            output = result.stdout.strip()
            if not output:
                raise RuntimeError("Claude CLI returned empty response")

            return LLMResponse(
                text=output,
                model=model,
                tokens_used=0,  # CLI doesn't report token usage
                latency_ms=latency_ms,
                provider=self.name,
            )

        except subprocess.TimeoutExpired:
            logger.error(f"Claude CLI timed out after {config.timeout}s")
            raise RuntimeError(f"Claude CLI timed out after {config.timeout}s")
        except FileNotFoundError:
            logger.error("Claude CLI not found")
            raise RuntimeError(
                "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
            )
        except Exception as e:
            logger.error(f"Claude CLI error: {e}")
            raise
