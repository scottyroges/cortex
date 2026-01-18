"""
LLM Provider Abstraction

Unified interface for multiple LLM providers with fallback chain support.
Used for session summarization and other LLM tasks in Cortex.
"""

from typing import Optional

from .provider import LLMProvider, LLMConfig, LLMResponse
from .anthropic_provider import AnthropicProvider
from .claude_cli_provider import ClaudeCLIProvider
from .ollama_provider import OllamaProvider
from .openrouter_provider import OpenRouterProvider

from logging_config import get_logger

logger = get_logger("llm")

__all__ = [
    "LLMProvider",
    "LLMConfig",
    "LLMResponse",
    "AnthropicProvider",
    "ClaudeCLIProvider",
    "OllamaProvider",
    "OpenRouterProvider",
    "get_provider",
    "get_available_providers",
]


def get_provider(config: Optional[dict] = None) -> LLMProvider:
    """
    Get an LLM provider based on configuration.

    Tries primary provider first, then fallback chain.

    Args:
        config: Configuration dict with 'llm' section containing:
            - primary_provider: str (anthropic, ollama, openrouter, claude-cli)
            - fallback_chain: list[str] of provider names to try if primary fails
            - Provider-specific config sections (anthropic, ollama, etc.)

    Returns:
        An available LLMProvider instance

    Raises:
        RuntimeError: If no providers are available
    """
    config = config or {}
    llm_config = config.get("llm", {})

    primary = llm_config.get("primary_provider", "claude-cli")
    fallback_chain = llm_config.get("fallback_chain", ["anthropic", "ollama"])

    providers_to_try = [primary] + [p for p in fallback_chain if p != primary]

    for provider_name in providers_to_try:
        try:
            provider = _create_provider(provider_name, llm_config)
            if provider.is_available():
                logger.info(f"Using LLM provider: {provider.name}")
                return provider
            else:
                logger.debug(f"Provider {provider_name} not available, trying next")
        except Exception as e:
            logger.debug(f"Failed to create provider {provider_name}: {e}")
            continue

    raise RuntimeError(
        "No LLM providers available. Please configure at least one of: "
        "anthropic (ANTHROPIC_API_KEY), ollama (local), openrouter (OPENROUTER_API_KEY), "
        "or claude-cli (install Claude CLI)"
    )


def get_available_providers(config: Optional[dict] = None) -> list[str]:
    """
    Get list of available provider names.

    Args:
        config: Configuration dict

    Returns:
        List of provider names that are currently available
    """
    config = config or {}
    llm_config = config.get("llm", {})

    available = []
    for provider_name in ["anthropic", "claude-cli", "ollama", "openrouter"]:
        try:
            provider = _create_provider(provider_name, llm_config)
            if provider.is_available():
                available.append(provider_name)
        except Exception:
            continue

    return available


def _create_provider(name: str, llm_config: dict) -> LLMProvider:
    """Create a provider instance by name."""
    if name == "anthropic":
        return AnthropicProvider(llm_config.get("anthropic", {}))
    elif name == "ollama":
        return OllamaProvider(llm_config.get("ollama", {}))
    elif name == "openrouter":
        return OpenRouterProvider(llm_config.get("openrouter", {}))
    elif name == "claude-cli":
        return ClaudeCLIProvider(llm_config.get("claude_cli", {}))
    else:
        raise ValueError(f"Unknown provider: {name}")
