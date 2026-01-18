"""
OpenRouter Provider

Uses the OpenRouter API for access to multiple model providers.
Requires OPENROUTER_API_KEY environment variable.
"""

import os
import time
from typing import Optional
import urllib.request
import urllib.error
import json

from .provider import LLMProvider, LLMConfig, LLMResponse
from logging_config import get_logger

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
                raise RuntimeError("OpenRouter API key not configured")

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

            req = urllib.request.Request(
                f"{self._base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                    "HTTP-Referer": "https://github.com/cortex-memory",
                    "X-Title": "Cortex Memory",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=config.timeout) as response:
                data = json.loads(response.read().decode())

            latency_ms = (time.time() - start_time) * 1000

            # Extract response
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("OpenRouter returned no choices")

            text = choices[0].get("message", {}).get("content", "")
            if not text:
                raise RuntimeError("OpenRouter returned empty response")

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

        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            logger.error(f"OpenRouter HTTP error {e.code}: {error_body}")
            raise RuntimeError(f"OpenRouter API error: {e.code} - {error_body}")
        except urllib.error.URLError as e:
            logger.error(f"OpenRouter connection error: {e}")
            raise RuntimeError(f"Failed to connect to OpenRouter: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"OpenRouter response parse error: {e}")
            raise RuntimeError(f"Invalid response from OpenRouter: {e}")
        except Exception as e:
            logger.error(f"OpenRouter error: {e}")
            raise
