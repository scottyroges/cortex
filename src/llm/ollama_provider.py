"""
Ollama Provider

Uses the Ollama local LLM server for generation.
No API key required - runs entirely locally.
"""

import time
from typing import Optional
import urllib.request
import urllib.error
import json

from .provider import LLMProvider, LLMConfig, LLMResponse
from logging_config import get_logger

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
            # Check if server is running
            req = urllib.request.Request(
                f"{self._base_url}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    # Check if we have any models
                    data = json.loads(response.read().decode())
                    models = data.get("models", [])
                    if models:
                        return True
                    logger.debug("Ollama running but no models installed")
                    return False
            return False
        except urllib.error.URLError as e:
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
            # Build request
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": config.temperature,
                    "num_predict": config.max_tokens,
                },
            }

            req = urllib.request.Request(
                f"{self._base_url}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=config.timeout) as response:
                data = json.loads(response.read().decode())

            latency_ms = (time.time() - start_time) * 1000

            text = data.get("response", "")
            if not text:
                raise RuntimeError("Ollama returned empty response")

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

        except urllib.error.URLError as e:
            logger.error(f"Ollama connection error: {e}")
            raise RuntimeError(f"Failed to connect to Ollama: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Ollama response parse error: {e}")
            raise RuntimeError(f"Invalid response from Ollama: {e}")
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            raise
