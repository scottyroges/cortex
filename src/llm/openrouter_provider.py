"""
OpenRouter Provider

Uses the OpenRouter API for access to multiple model providers.
Requires OPENROUTER_API_KEY environment variable.
"""

import os
import time
from typing import Optional

from logging_config import get_logger
from src.exceptions import LLMConnectionError, LLMResponseError, LLMTimeoutError
from src.http.http_client import HTTPError, http_post

from .provider import LLMConfig, LLMProvider, LLMResponse

logger = get_logger("llm.openrouter")


class OpenRouterProvider(LLMProvider):
    """
    LLM provider using OpenRouter API.

    Configuration:
        model: Model to use (default: anthropic/claude-3-haiku)
        base_url: API URL (default: https://openrouter.ai/api/v1)

    Environment:
        OPENROUTER_API_KEY: Required API key
    """

    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}
        self._base_url = self._config.get(
            "base_url", "https://openrouter.ai/api/v1"
        )
        self._api_key = None

    @property
    def name(self) -> str:
        return "openrouter"

    @property
    def default_model(self) -> str:
        return self._config.get("model", "anthropic/claude-3-haiku")

    def is_available(self) -> bool:
        """Check if API key is set."""
        self._api_key = os.environ.get("OPENROUTER_API_KEY")
        if not self._api_key:
            logger.debug("OPENROUTER_API_KEY not set")
            return False
        return True

    def generate(self, prompt: str, config: Optional[LLMConfig] = None) -> LLMResponse:
        """Generate completion using OpenRouter API."""
        if self._api_key is None:
            if not self.is_available():
                raise LLMConnectionError("OpenRouter API key not configured")

        config = config or LLMConfig()
        model = config.model or self.default_model

        start_time = time.time()

        try:
            # Build request (OpenAI-compatible format)
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
            }

            response = http_post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "HTTP-Referer": "https://github.com/cortex-memory",
                    "X-Title": "Cortex Memory",
                },
                timeout=config.timeout,
            )
            data = response.json()

            latency_ms = (time.time() - start_time) * 1000

            # Extract response
            choices = data.get("choices", [])
            if not choices:
                raise LLMResponseError("OpenRouter returned no choices")

            text = choices[0].get("message", {}).get("content", "")
            if not text:
                raise LLMResponseError("OpenRouter returned empty response")

            # Extract token usage
            tokens_used = 0
            usage = data.get("usage", {})
            if usage:
                tokens_used = usage.get("total_tokens", 0)

            return LLMResponse(
                text=text,
                model=data.get("model", model),
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                provider=self.name,
            )

        except LLMConnectionError:
            raise
        except LLMTimeoutError:
            raise
        except HTTPError as e:
            logger.error(f"OpenRouter HTTP error: {e}")
            raise LLMResponseError(f"OpenRouter API error: {e}") from e
        except Exception as e:
            logger.error(f"OpenRouter error: {e}")
            raise
