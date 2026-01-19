"""
Contextual Header Generation

Generate descriptive headers for code chunks using various providers.

This module provides backward-compatible functions for header generation
and also integrates with the new LLM provider abstraction.
"""

import subprocess
from typing import Optional

from anthropic import Anthropic
from langchain_text_splitters import Language
from tenacity import retry, stop_after_attempt, wait_exponential

from logging_config import get_logger

logger = get_logger("ingest.headers")

# Singleton for LLM provider (lazy initialized)
_llm_provider = None


def get_llm_provider():
    """Get or create the LLM provider singleton."""
    global _llm_provider
    if _llm_provider is None:
        try:
            from src.llm import get_provider

            _llm_provider = get_provider()
        except Exception as e:
            logger.debug(f"Failed to initialize LLM provider: {e}")
            _llm_provider = None
    return _llm_provider


# Header prompt template used by all providers
HEADER_PROMPT_TEMPLATE = """Analyze this {language} code chunk from {file_path} and provide a brief (1-2 sentence) description of what it does. Focus on the purpose and key functionality.

Code:
```{language}
{chunk}
```

Respond with only the description, no formatting or prefixes."""


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=60),
    stop=stop_after_attempt(3),
)
def generate_header_with_anthropic(
    chunk: str,
    file_path: str,
    language: str,
    anthropic_client: Anthropic,
) -> str:
    """
    Generate a contextual header using the Anthropic API (Haiku).

    Args:
        chunk: Code chunk to describe
        file_path: Path to the source file
        language: Programming language name
        anthropic_client: Anthropic client instance

    Returns:
        Generated description
    """
    prompt = HEADER_PROMPT_TEMPLATE.format(
        language=language,
        file_path=file_path,
        chunk=chunk[:2000],
    )

    try:
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Anthropic API error: {e}")
        return f"Code snippet from {file_path}"


def generate_header_with_claude_cli(
    chunk: str,
    file_path: str,
    language: str,
) -> str:
    """
    Generate a contextual header using the Claude CLI.

    Args:
        chunk: Code chunk to describe
        file_path: Path to the source file
        language: Programming language name

    Returns:
        Generated description
    """
    prompt = HEADER_PROMPT_TEMPLATE.format(
        language=language,
        file_path=file_path,
        chunk=chunk[:2000],
    )

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "haiku"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        logger.warning(f"Claude CLI error: {result.stderr}")
        return f"Code snippet from {file_path}"
    except FileNotFoundError:
        logger.warning(
            "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
        )
        return f"Code snippet from {file_path}"
    except subprocess.TimeoutExpired:
        logger.warning("Claude CLI timed out")
        return f"Code snippet from {file_path}"
    except Exception as e:
        logger.warning(f"Claude CLI error: {e}")
        return f"Code snippet from {file_path}"


def generate_header_with_provider(
    chunk: str,
    file_path: str,
    language: str,
) -> str:
    """
    Generate a contextual header using the unified LLM provider abstraction.

    This function uses the configured LLM provider (with fallback chain)
    to generate code headers. Falls back to simple headers if no provider
    is available.

    Args:
        chunk: Code chunk to describe
        file_path: Path to the source file
        language: Programming language name

    Returns:
        Generated description or simple fallback
    """
    provider = get_llm_provider()
    if provider is None:
        return f"Code from {file_path}"

    try:
        return provider.generate_code_header(chunk, file_path, language)
    except Exception as e:
        logger.warning(f"LLM provider error: {e}")
        return f"Code snippet from {file_path}"


def generate_header_sync(
    chunk: str,
    file_path: str,
    language: Optional[Language],
    anthropic_client: Optional[Anthropic] = None,
    llm_provider: str = "none",
) -> str:
    """
    Generate header for a chunk using the specified provider.

    Args:
        chunk: The code chunk
        file_path: Path to the source file
        language: Detected language
        anthropic_client: Anthropic client (for "anthropic" provider)
        llm_provider: One of "anthropic", "claude-cli", "auto", or "none"
            - "auto": Use the unified LLM provider abstraction

    Returns:
        Generated or simple header text
    """
    lang_str = language.value if language else "text"

    if llm_provider == "anthropic" and anthropic_client:
        return generate_header_with_anthropic(chunk, file_path, lang_str, anthropic_client)
    elif llm_provider == "claude-cli":
        return generate_header_with_claude_cli(chunk, file_path, lang_str)
    elif llm_provider == "auto":
        return generate_header_with_provider(chunk, file_path, lang_str)

    # Simple fallback header
    return f"Code from {file_path}"
