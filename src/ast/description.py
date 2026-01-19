"""
LLM Description Generator

Generates search-optimized descriptions for source files using configurable LLM providers.
"""

from typing import Optional

from logging_config import get_logger
from src.ast.models import FileMetadata
from src.llm import LLMConfig, LLMProvider, get_provider

logger = get_logger("ast.description")


# Prompt template for generating file descriptions
DESCRIPTION_PROMPT = """Analyze this {language} code from {file_path}.

Write a dense, search-optimized summary (2-3 sentences) that includes:
1. The main responsibility (e.g., "Handles user authentication")
2. Key algorithms or patterns used (e.g., "Implements sliding window rate limiting")
3. Specific technologies/libraries (e.g., "Uses Stripe API for billing")
4. Any validation constraints if present (e.g., "Validates email format, requires min 8 char password")

Be specific. "User controller" is bad. "REST endpoints for user CRUD with JWT auth and Stripe billing integration" is good.

Code:
```{language}
{code}
```

Write ONLY the description, no formatting or prefixes:"""


def generate_description(
    file_path: str,
    language: str,
    source_code: str,
    exports: list[str],
    provider: Optional[LLMProvider] = None,
    config: Optional[dict] = None,
) -> str:
    """
    Generate a search-optimized description for a source file.

    Args:
        file_path: Path to the source file
        language: Programming language
        source_code: Full source code content
        exports: List of exported symbol names
        provider: Optional LLM provider (uses get_provider if None)
        config: Optional configuration for get_provider

    Returns:
        Generated description or fallback description on error
    """
    # Get provider if not provided
    if provider is None:
        try:
            provider = get_provider(config)
        except RuntimeError as e:
            logger.warning(f"No LLM provider available: {e}")
            return _fallback_description(file_path, language, exports)

    # Truncate source if too long (keep first 4000 chars)
    truncated = source_code[:4000] if len(source_code) > 4000 else source_code

    # Build prompt
    prompt = DESCRIPTION_PROMPT.format(
        language=language,
        file_path=file_path,
        code=truncated,
    )

    try:
        llm_config = LLMConfig(max_tokens=200, temperature=0.2)
        response = provider.generate(prompt, llm_config)
        description = response.text.strip()

        # Validate description isn't empty or too generic
        if len(description) < 20:
            logger.warning(f"Generated description too short for {file_path}")
            return _fallback_description(file_path, language, exports)

        logger.debug(f"Generated description for {file_path}: {description[:50]}...")
        return description

    except Exception as e:
        logger.warning(f"Failed to generate description for {file_path}: {e}")
        return _fallback_description(file_path, language, exports)


def generate_description_from_metadata(
    metadata: FileMetadata,
    source_code: str,
    provider: Optional[LLMProvider] = None,
    config: Optional[dict] = None,
) -> str:
    """
    Generate description from FileMetadata.

    Convenience wrapper that extracts fields from metadata.

    Args:
        metadata: FileMetadata with extracted info
        source_code: Full source code content
        provider: Optional LLM provider
        config: Optional configuration

    Returns:
        Generated description
    """
    return generate_description(
        file_path=metadata.file_path,
        language=metadata.language,
        source_code=source_code,
        exports=metadata.get_export_list(),
        provider=provider,
        config=config,
    )


def _fallback_description(file_path: str, language: str, exports: list[str]) -> str:
    """
    Generate a basic fallback description when LLM is unavailable.

    Args:
        file_path: Path to the source file
        language: Programming language
        exports: List of exported symbols

    Returns:
        Basic description string
    """
    if exports:
        export_list = ", ".join(exports[:5])
        if len(exports) > 5:
            export_list += f" (+{len(exports) - 5} more)"
        return f"{file_path} - {language} file with exports: {export_list}"
    else:
        return f"{file_path} - {language} file"


async def generate_descriptions_batch(
    files: list[tuple[str, str, str, list[str]]],  # (path, language, source, exports)
    provider: Optional[LLMProvider] = None,
    config: Optional[dict] = None,
    max_concurrent: int = 5,
) -> dict[str, str]:
    """
    Generate descriptions for multiple files.

    Note: This is a synchronous batch implementation for now.
    True async would require async LLM providers.

    Args:
        files: List of (file_path, language, source_code, exports) tuples
        provider: Optional LLM provider
        config: Optional configuration
        max_concurrent: Max concurrent requests (reserved for future async)

    Returns:
        Dict mapping file_path to description
    """
    if provider is None:
        try:
            provider = get_provider(config)
        except RuntimeError as e:
            logger.warning(f"No LLM provider available for batch: {e}")
            return {
                path: _fallback_description(path, lang, exports)
                for path, lang, _, exports in files
            }

    results = {}
    for file_path, language, source_code, exports in files:
        description = generate_description(
            file_path=file_path,
            language=language,
            source_code=source_code,
            exports=exports,
            provider=provider,
        )
        results[file_path] = description

    return results
