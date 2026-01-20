"""
Cortex Exception Hierarchy

Centralized exception classes for structured error handling across the codebase.
All Cortex-specific exceptions inherit from CortexError.

Usage:
    from src.exceptions import CortexError, IngestError, SearchError

    try:
        ingest_codebase(path)
    except IngestError as e:
        logger.error(f"Ingest failed: {e}")
"""


class CortexError(Exception):
    """Base exception for all Cortex errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} ({self.details})"
        return self.message


# =============================================================================
# Configuration Errors
# =============================================================================


class ConfigurationError(CortexError):
    """Error in Cortex configuration."""

    pass


class MissingConfigError(ConfigurationError):
    """Required configuration value is missing."""

    pass


# =============================================================================
# Storage Errors
# =============================================================================


class StorageError(CortexError):
    """Base class for storage-related errors."""

    pass


class CollectionError(StorageError):
    """Error with ChromaDB collection operations."""

    pass


class MigrationError(StorageError):
    """Error during schema migration."""

    pass


# =============================================================================
# Ingest Errors
# =============================================================================


class IngestError(CortexError):
    """Base class for ingestion errors."""

    pass


class IngestFileNotFoundError(IngestError):
    """File to ingest was not found."""

    pass


class ParseError(IngestError):
    """Error parsing file content (AST, JSON, etc.)."""

    pass


class ChunkingError(IngestError):
    """Error during code chunking."""

    pass


# =============================================================================
# Search Errors
# =============================================================================


class SearchError(CortexError):
    """Base class for search-related errors."""

    pass


class SearchIndexError(SearchError):
    """Error building or querying search index."""

    pass


class RerankError(SearchError):
    """Error during result reranking."""

    pass


# =============================================================================
# Git Errors
# =============================================================================


class GitError(CortexError):
    """Base class for git-related errors."""

    pass


class GitCommandError(GitError):
    """Git command failed to execute."""

    def __init__(
        self,
        message: str,
        command: list[str] | None = None,
        returncode: int | None = None,
        stderr: str | None = None,
    ):
        details = {}
        if command:
            details["command"] = " ".join(command)
        if returncode is not None:
            details["returncode"] = returncode
        if stderr:
            details["stderr"] = stderr
        super().__init__(message, details)
        self.command = command
        self.returncode = returncode
        self.stderr = stderr


class NotAGitRepoError(GitError):
    """Path is not a git repository."""

    pass


# =============================================================================
# HTTP/Client Errors
# =============================================================================


class ClientError(CortexError):
    """Base class for HTTP client errors."""

    pass


class HTTPRequestError(ClientError):
    """HTTP request failed."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_text: str | None = None,
    ):
        details = {}
        if status_code is not None:
            details["status_code"] = status_code
        if response_text:
            details["response_text"] = response_text[:200]
        super().__init__(message, details)
        self.status_code = status_code
        self.response_text = response_text


class HTTPConnectionError(ClientError):
    """Failed to connect to HTTP endpoint."""

    pass


class HTTPTimeoutError(ClientError):
    """HTTP request timed out."""

    pass


class DaemonNotRunningError(ClientError):
    """Cortex daemon is not running."""

    pass


class DaemonTimeoutError(ClientError):
    """Request to daemon timed out."""

    pass


class APIError(ClientError):
    """API returned an error response."""

    def __init__(self, message: str, status_code: int | None = None):
        details = {"status_code": status_code} if status_code else {}
        super().__init__(message, details)
        self.status_code = status_code


# =============================================================================
# LLM Provider Errors
# =============================================================================


class LLMError(CortexError):
    """Base class for LLM provider errors."""

    pass


class LLMConnectionError(LLMError):
    """Failed to connect to LLM provider."""

    pass


class LLMTimeoutError(LLMError):
    """LLM request timed out."""

    pass


class LLMResponseError(LLMError):
    """Invalid or unexpected response from LLM."""

    pass


# =============================================================================
# Initiative/Tool Errors
# =============================================================================


class ToolError(CortexError):
    """Base class for MCP tool errors."""

    pass


class InitiativeNotFoundError(ToolError):
    """Initiative with given ID/name not found."""

    pass


class ValidationError(ToolError):
    """Input validation failed."""

    pass


# =============================================================================
# Autocapture Errors
# =============================================================================


class AutocaptureError(CortexError):
    """Base class for autocapture errors."""

    pass


class TranscriptParseError(AutocaptureError):
    """Error parsing session transcript."""

    pass


class HookError(AutocaptureError):
    """Error in hook execution."""

    pass
