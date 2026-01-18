"""
Ollama Provider

Uses the Ollama local LLM server for generation.
No API key required - runs entirely locally.
"""

import time
from typing import Optional

from logging_config import get_logger
from src.exceptions import LLMConnectionError, LLMResponseError, LLMTimeoutError
from src.http.http_client import HTTPError, http_json_get, http_json_post

from .provider import LLMConfig, LLMProvider, LLMResponse

logger = get_logger("llm.ollama")


class OllamaProvider(LLMProvider):
    """
    LLM provider using Ollama local server.

    Configuration:
        model: Model to use (default: llama3.2)
        base_url: Ollama server URL (default: http://localhost:11434)

    Requires:
        Ollama to be installed and running locally
    """

    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}
        self._base_url = self._config.get("base_url", "http://localhost:11434")

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def default_model(self) -> str:
        return self._config.get("model", "llama3.2")

    def is_available(self) -> bool:
        """Check if Ollama server is running and accessible."""
        try:
            data = http_json_get(f"{self._base_url}/api/tags", timeout=5)
            models = data.get("models", [])
            if models:
                return True
            logger.debug("Ollama running but no models installed")
            return False
        except (LLMConnectionError, LLMTimeoutError) as e:
            logger.debug(f"Ollama not reachable: {e}")
            return False
        except Exception as e:
            logger.debug(f"Ollama check failed: {e}")
            return False

    def generate(self, prompt: str, config: Optional[LLMConfig] = None) -> LLMResponse:
        """Generate completion using Ollama API."""
        config = config or LLMConfig()
        model = config.model or self.default_model

        start_time = time.time()

        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": config.temperature,
                    "num_predict": config.max_tokens,
                },
            }

            data = http_json_post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=config.timeout,
            )

            latency_ms = (time.time() - start_time) * 1000

            text = data.get("response", "")
            if not text:
                raise LLMResponseError("Ollama returned empty response")

            # Extract token counts if available
            tokens_used = 0
            if "prompt_eval_count" in data and "eval_count" in data:
                tokens_used = data["prompt_eval_count"] + data["eval_count"]

            return LLMResponse(
                text=text,
                model=model,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                provider=self.name,
            )

        except LLMConnectionError as e:
            logger.error(f"Ollama connection error: {e}")
            raise
        except LLMTimeoutError as e:
            logger.error(f"Ollama timeout: {e}")
            raise
        except HTTPError as e:
            logger.error(f"Ollama HTTP error: {e}")
            raise LLMResponseError(f"Ollama API error: {e}") from e
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            raise
