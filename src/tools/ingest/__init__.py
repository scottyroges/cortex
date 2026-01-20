"""
Cortex Ingestion Engine

Metadata-first codebase ingestion with delta sync.
"""

from src.tools.ingest.engine import ingest_codebase, select_delta_strategy
from src.tools.ingest.skeleton import generate_tree_structure, get_skeleton, store_skeleton
from src.tools.ingest.walker import compute_file_hash, get_changed_files, walk_codebase
from src.tools.ingest.ingest import ASYNC_FILE_THRESHOLD, ingest_code_into_cortex

__all__ = [
    # Walker
    "walk_codebase",
    "get_changed_files",
    "compute_file_hash",
    # Skeleton
    "generate_tree_structure",
    "store_skeleton",
    "get_skeleton",
    # Engine
    "ingest_codebase",
    "select_delta_strategy",
    # Tool
    "ingest_code_into_cortex",
    # Constants
    "ASYNC_FILE_THRESHOLD",
]
