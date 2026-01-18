"""
Anthropic API Provider

Uses the Anthropic SDK for direct API access.
Requires ANTHROPIC_API_KEY environment variable.
"""

import os
import time
from typing import Optional

from .provider import LLMProvider, LLMConfig, LLMResponse
from logging_config import get_logger

logger = get_logger("llm.anthropic")


class AnthropicProvider(LLMProvider):
    """
    LLM provider using the Anthropic API directly.

    Configuration:
        model: Model to use (default: claude-3-haiku-20240307)

    Environment:
        ANTHROPIC_API_KEY: Required API key
    """

    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}
        self._client = None

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return self._config.get("model", "claude-3-haiku-20240307")

    def is_available(self) -> bool:
        """Check if API key is set and client can be created."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return False

        try:
            # Lazy import to avoid dependency if not used
            from anthropic import Anthropic

            self._client = Anthropic(api_key=api_key)
            return True
        except ImportError:
            logger.debug("anthropic package not installed")
            return False
        except Exception as e:
            logger.debug(f"Failed to create Anthropic client: {e}")
            return False

    def generate(self, prompt: str, config: Optional[LLMConfig] = None) -> LLMResponse:
        """Generate completion using Anthropic API."""
        if self._client is None:
            if not self.is_available():
                raise RuntimeError("Anthropic provider not available")

        config = config or LLMConfig()
        model = config.model or self.default_model

        start_time = time.time()

        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                messages=[{"role": "user", "content": prompt}],
            )

            latency_ms = (time.time() - start_time) * 1000

            # Extract token usage
            tokens_used = 0
            if hasattr(response, "usage"):
                tokens_used = (
                    getattr(response.usage, "input_tokens", 0)
                    + getattr(response.usage, "output_tokens", 0)
                )

            return LLMResponse(
                text=response.content[0].text,
                model=model,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                provider=self.name,
            )

        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise
