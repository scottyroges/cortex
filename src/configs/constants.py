"""
Cortex Constants

Static configuration values that rarely change: binary extensions,
file size limits, and timeout configuration.
"""

# --- Binary Extensions ---
# File extensions that should be skipped during indexing

BINARY_EXTENSIONS = {
    ".exe",
    ".bin",
    ".so",
    ".dylib",
    ".dll",
    ".o",
    ".a",
    ".lib",
    # Images
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".webp",
    # Media
    ".mp3",
    ".mp4",
    ".wav",
    ".avi",
    ".mov",
    ".webm",
    # Archives
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    # Documents
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    # Fonts
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    # Databases
    ".db",
    ".sqlite",
    ".sqlite3",
}

# --- File Size Limits ---

MAX_FILE_SIZE = 1_000_000  # 1MB max file size

# --- Timeout Configuration ---
# Centralized timeout values (in seconds unless noted)

TIMEOUTS = {
    # Git operations
    "git_command": 10,  # Default git command timeout
    "git_diff": 30,  # Git diff for large repos
    # HTTP requests
    "http_default": 10,  # Default HTTP request timeout
    "http_health_check": 5,  # Health check endpoints
    "http_llm_request": 120,  # LLM API requests (can be slow)
    # LLM providers
    "llm_availability_check": 5,  # Provider availability check
    # Ingest operations
    "ingest_headers": 30,  # Header provider timeout
    "ingest_skeleton": 10,  # Skeleton generation
    # Summarization
    "summarize_session": 60,  # Session summarization
    # Hook execution (milliseconds)
    "hook_execution_ms": 15000,  # Claude Code hook timeout
}


def get_timeout(key: str, default: int | float | None = None) -> int | float:
    """
    Get a timeout value by key.

    Args:
        key: Timeout key from TIMEOUTS dict
        default: Default value if key not found

    Returns:
        Timeout value in seconds (or milliseconds for hook_execution_ms)
    """
    if default is None:
        default = TIMEOUTS.get("http_default", 10)
    return TIMEOUTS.get(key, default)
