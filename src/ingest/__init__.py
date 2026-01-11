"""
Cortex Ingestion Engine

AST-aware code chunking, file walking, and codebase ingestion.
"""

from src.ingest.chunker import (
    EXTENSION_TO_LANGUAGE,
    chunk_code_file,
    detect_language,
    extract_scope_from_chunk,
)
from src.ingest.engine import ingest_codebase, ingest_file, ingest_files
from src.ingest.headers import (
    HEADER_PROMPT_TEMPLATE,
    generate_header_sync,
    generate_header_with_anthropic,
    generate_header_with_claude_cli,
)
from src.ingest.skeleton import generate_tree_structure, store_skeleton
from src.ingest.walker import compute_file_hash, get_changed_files, walk_codebase

__all__ = [
    # Walker
    "walk_codebase",
    "get_changed_files",
    "compute_file_hash",
    # Chunker
    "detect_language",
    "extract_scope_from_chunk",
    "chunk_code_file",
    "EXTENSION_TO_LANGUAGE",
    # Headers
    "HEADER_PROMPT_TEMPLATE",
    "generate_header_sync",
    "generate_header_with_anthropic",
    "generate_header_with_claude_cli",
    # Skeleton
    "generate_tree_structure",
    "store_skeleton",
    # Engine
    "ingest_file",
    "ingest_codebase",
    "ingest_files",
]
