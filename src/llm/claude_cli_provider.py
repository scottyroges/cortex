"""
Claude CLI Provider

Uses the `claude` command-line tool for generation.
Inherits authentication from the CLI's own config.

When CORTEX_SUMMARIZER_URL is set (e.g., in Docker), uses an HTTP
proxy on the host instead of calling the CLI directly.
"""

import os
import shutil
import subprocess
import time
from typing import Optional

from logging_config import get_logger
from src.exceptions import LLMConnectionError, LLMResponseError, LLMTimeoutError
from src.http.http_client import HTTPError, http_get, http_json_post

from .provider import LLMConfig, LLMProvider, LLMResponse

logger = get_logger("llm.claude_cli")

# Summarizer proxy URL (set when running in Docker with claude-cli provider)
SUMMARIZER_URL = os.environ.get("CORTEX_SUMMARIZER_URL")


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
        """Check if claude CLI or summarizer proxy is accessible."""
        # If summarizer URL is set (Docker mode), check if proxy is reachable
        if SUMMARIZER_URL:
            try:
                response = http_get(f"{SUMMARIZER_URL}/health", timeout=5, raise_for_status=False)
                return response.status_code == 200
            except Exception as e:
                logger.debug(f"Summarizer proxy not available: {e}")
                return False

        # Otherwise check for local CLI
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
        """Generate completion using Claude CLI or summarizer proxy."""
        config = config or LLMConfig()
        model = config.model or self.default_model
        start_time = time.time()

        # Use summarizer proxy if available (Docker mode)
        if SUMMARIZER_URL:
            return self._generate_via_proxy(prompt, model, config.timeout, start_time, config.max_tokens)

        # Otherwise use local CLI
        return self._generate_via_cli(prompt, model, config.timeout, start_time)

    def _generate_via_proxy(
        self, prompt: str, model: str, timeout: int, start_time: float, max_tokens: int = 1024
    ) -> LLMResponse:
        """Generate completion via the summarizer HTTP proxy using /generate endpoint."""
        try:
            result = http_json_post(
                f"{SUMMARIZER_URL}/generate",
                json={"prompt": prompt, "model": model, "max_tokens": max_tokens},
                timeout=timeout,
            )

            latency_ms = (time.time() - start_time) * 1000

            if "error" in result:
                raise LLMResponseError(f"Proxy error: {result['error']}")

            text = result.get("text", "")
            if not text:
                raise LLMResponseError("Proxy returned empty response")

            return LLMResponse(
                text=text,
                model=model,
                tokens_used=0,
                latency_ms=latency_ms,
                provider=f"{self.name}+proxy",
            )

        except LLMConnectionError as e:
            logger.error(f"Summarizer proxy connection error: {e}")
            raise
        except LLMTimeoutError as e:
            logger.error(f"Summarizer proxy timeout: {e}")
            raise
        except HTTPError as e:
            logger.error(f"Summarizer proxy HTTP error: {e}")
            raise LLMResponseError(f"Summarizer proxy error: {e}") from e
        except LLMResponseError:
            raise
        except Exception as e:
            logger.error(f"Summarizer proxy error: {e}")
            raise

    def _generate_via_cli(
        self, prompt: str, model: str, timeout: int, start_time: float
    ) -> LLMResponse:
        """Generate completion using local Claude CLI."""
        if self._cli_path is None:
            if not self.is_available():
                raise LLMConnectionError("Claude CLI not available")

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
                timeout=timeout,
            )

            latency_ms = (time.time() - start_time) * 1000

            if result.returncode != 0:
                error_msg = result.stderr.strip() or "Unknown error"
                raise LLMResponseError(f"Claude CLI failed: {error_msg}")

            output = result.stdout.strip()
            if not output:
                raise LLMResponseError("Claude CLI returned empty response")

            return LLMResponse(
                text=output,
                model=model,
                tokens_used=0,  # CLI doesn't report token usage
                latency_ms=latency_ms,
                provider=self.name,
            )

        except subprocess.TimeoutExpired:
            logger.error(f"Claude CLI timed out after {timeout}s")
            raise LLMTimeoutError(f"Claude CLI timed out after {timeout}s")
        except FileNotFoundError:
            logger.error("Claude CLI not found")
            raise LLMConnectionError(
                "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
            )
        except (LLMConnectionError, LLMTimeoutError, LLMResponseError):
            raise
        except Exception as e:
            logger.error(f"Claude CLI error: {e}")
            raise

    def summarize_session(self, transcript_text: str, max_chars: int = 100000) -> str:
        """
        Generate a session summary using the provider.

        Override to use the summarizer proxy's /summarize endpoint directly,
        which has its own optimized prompt.
        """
        # Truncate if needed
        if len(transcript_text) > max_chars:
            transcript_text = transcript_text[:max_chars] + "\n\n[... transcript truncated ...]"

        # Use proxy if available - it has its own summarization prompt
        if SUMMARIZER_URL:
            return self._summarize_via_proxy(transcript_text, self.default_model)

        # Otherwise use the parent class implementation
        return super().summarize_session(transcript_text, max_chars)

    def _summarize_via_proxy(self, transcript: str, model: str) -> str:
        """Use the /summarize endpoint which has its own optimized prompt."""
        start_time = time.time()
        try:
            result = http_json_post(
                f"{SUMMARIZER_URL}/summarize",
                json={"transcript": transcript, "model": model},
                timeout=60,
            )

            if "error" in result:
                raise LLMResponseError(f"Summarizer proxy error: {result['error']}")

            summary = result.get("summary", "")
            if not summary:
                raise LLMResponseError("Summarizer proxy returned empty response")

            latency_ms = (time.time() - start_time) * 1000
            logger.debug(f"Session summarized via proxy in {latency_ms:.0f}ms")
            return summary.strip()

        except Exception as e:
            logger.error(f"Summarization via proxy failed: {e}")
            raise
