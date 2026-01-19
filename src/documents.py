"""
Document Type Definitions for Cortex

Central definition of all document types, their metadata schemas, and related constants.
This module provides compile-time type checking and runtime validation for documents.

Document Categories:
- Navigation (The Map): file_metadata, dependency, skeleton
- Understanding & Usage (The Manual): entry_point, data_contract, idiom
- Semantic Memory (The Brain): note, session_summary, insight, tech_stack, initiative
"""

from enum import Enum
from typing import Literal, TypedDict, get_args


# =============================================================================
# Document Type Literal
# =============================================================================

DocumentType = Literal[
    # Navigation (The Map) - tells the agent WHERE to look
    "file_metadata",
    "dependency",
    "skeleton",
    # Understanding & Usage (The Manual) - tells the agent HOW to use
    "entry_point",
    "data_contract",
    "idiom",
    # Semantic Memory (The Brain) - captures decisions and understanding
    "note",
    "session_summary",
    "insight",
    "tech_stack",
    "initiative",
]

# All valid document types as a tuple (for runtime validation)
ALL_DOCUMENT_TYPES: tuple[str, ...] = get_args(DocumentType)


# =============================================================================
# Type Categories
# =============================================================================

class TypeCategory(str, Enum):
    """Categories of document types for filtering and scoring logic."""

    NAVIGATION = "navigation"  # file_metadata, dependency, skeleton
    USAGE = "usage"  # entry_point, data_contract, idiom
    MEMORY = "memory"  # note, session_summary, insight
    CONTEXT = "context"  # tech_stack, initiative


TYPE_CATEGORIES: dict[DocumentType, TypeCategory] = {
    # Navigation
    "file_metadata": TypeCategory.NAVIGATION,
    "dependency": TypeCategory.NAVIGATION,
    "skeleton": TypeCategory.NAVIGATION,
    # Usage
    "entry_point": TypeCategory.USAGE,
    "data_contract": TypeCategory.USAGE,
    "idiom": TypeCategory.USAGE,
    # Memory
    "note": TypeCategory.MEMORY,
    "session_summary": TypeCategory.MEMORY,
    "insight": TypeCategory.MEMORY,
    # Context
    "tech_stack": TypeCategory.CONTEXT,
    "initiative": TypeCategory.CONTEXT,
}


# =============================================================================
# TypedDict Metadata Schemas
# =============================================================================

class BaseMetadata(TypedDict, total=False):
    """Base metadata fields common to all document types."""

    type: str  # DocumentType (str for ChromaDB compatibility)
    repository: str
    branch: str
    created_at: str  # ISO 8601
    indexed_at: str  # ISO 8601
    status: str  # active, deprecated


class FileMetadataDoc(BaseMetadata):
    """Metadata for file_metadata documents - the primary search anchor."""

    file_path: str
    language: str
    description: str  # AI-generated behavioral summary
    exports: str  # CSV list of exported symbols (limited to 20)
    is_entry_point: bool
    is_barrel: bool
    is_test: bool
    is_config: bool
    entry_point_type: str  # main, api_route, cli, event_handler
    related_tests: str  # CSV of test file paths
    file_hash: str  # MD5 for staleness tracking


class DependencyDoc(BaseMetadata):
    """Metadata for dependency documents - the impact graph."""

    file_path: str
    imports: str  # CSV list of imported files
    imported_by: str  # CSV list of files that import this
    import_count: int
    imported_by_count: int
    impact_tier: str  # High (>5 dependents), Medium (2-5), Low (0-1)


class SkeletonDoc(BaseMetadata):
    """Metadata for skeleton documents - the directory structure."""

    total_files: int
    total_dirs: int


class EntryPointDoc(BaseMetadata):
    """Metadata for entry_point documents - the triggers."""

    file_path: str
    entry_type: str  # main, api_route, cli, event_handler
    language: str
    triggers: str  # JSON array: [{"method": "POST", "route": "/v1/ingest"}]
    summary: str  # User-facing behavior description
    file_hash: str


class DataContractDoc(BaseMetadata):
    """Metadata for data_contract documents - the shapes."""

    name: str  # Type/interface name
    file_path: str
    contract_type: str  # interface, class, dataclass, type_alias, pydantic_model
    language: str
    fields: str  # CSV: name1:type1,name2:type2 (limited to 20)
    validation_rules: str  # JSON array of validation rules


class IdiomDoc(BaseMetadata):
    """Metadata for idiom documents - the gold standard coding patterns."""

    title: str
    language: str
    description: str  # What this idiom enforces
    related_files: str  # JSON array of file paths


class NoteDoc(BaseMetadata):
    """Metadata for note documents - decisions and learnings."""

    title: str
    tags: str  # JSON array
    initiative_id: str
    initiative_name: str
    verified_at: str  # ISO 8601


class InsightDoc(BaseMetadata):
    """Metadata for insight documents - understanding anchored to files."""

    title: str
    tags: str  # JSON array
    files: str  # JSON array (required, non-empty)
    file_hashes: str  # JSON dict for staleness tracking
    initiative_id: str
    initiative_name: str
    verified_at: str  # ISO 8601
    last_validation_result: str  # still_valid, partially_valid, no_longer_valid


class SessionSummaryDoc(BaseMetadata):
    """Metadata for session_summary documents - end-of-session context."""

    files: str  # JSON array of changed files
    initiative_id: str
    initiative_name: str


class TechStackDoc(BaseMetadata):
    """Metadata for tech_stack documents - repository context."""

    pass  # Uses only base fields


class InitiativeDoc(BaseMetadata):
    """Metadata for initiative documents - multi-session workstreams."""

    name: str
    goal: str
    completed_at: str  # ISO 8601, if completed
    completion_summary: str


# =============================================================================
# Constants
# =============================================================================

# Types that should be filtered by branch (code-specific)
BRANCH_FILTERED_TYPES: set[str] = {
    "skeleton",
    "file_metadata",
    "data_contract",
    "entry_point",
    "dependency",
}

# Types that receive recency boosting (understanding decays, code doesn't)
RECENCY_BOOSTED_TYPES: set[str] = {
    "note",
    "session_summary",
}

# Type multipliers for search scoring
# Philosophy: "Code can be grepped. Understanding cannot."
TYPE_MULTIPLIERS: dict[str, float] = {
    # Understanding (highest value - irreplaceable)
    "insight": 2.0,
    "note": 1.5,
    "session_summary": 1.5,
    # Usage (high value - tells agent how)
    "entry_point": 1.4,
    "file_metadata": 1.3,
    "data_contract": 1.3,
    "idiom": 1.3,
    # Context
    "tech_stack": 1.2,
    # Standard
    "dependency": 1.0,
    "skeleton": 1.0,
    "initiative": 1.0,
}

# Search presets for common query patterns
SEARCH_PRESETS: dict[str, list[str]] = {
    # "Why did we...?" / "What was decided...?"
    "understanding": ["insight", "note", "session_summary"],
    # "How do I...?" / "Where is...?"
    "navigation": ["file_metadata", "entry_point", "data_contract", "idiom"],
    # "What's the architecture...?"
    "structure": ["file_metadata", "dependency", "skeleton"],
    # "What calls...?" / "What breaks if...?"
    "trace": ["entry_point", "dependency", "data_contract"],
    # Combined understanding + navigation
    "memory": ["insight", "note", "session_summary", "file_metadata"],
}

# Metadata-only types (no semantic memory, cross-initiative)
METADATA_ONLY_TYPES: set[str] = {
    "file_metadata",
    "data_contract",
    "entry_point",
    "dependency",
    "skeleton",
}


# =============================================================================
# Validation
# =============================================================================

def validate_document_type(type_str: str) -> DocumentType:
    """
    Validate and return a document type.

    Args:
        type_str: String to validate as a document type

    Returns:
        The validated DocumentType

    Raises:
        ValueError: If type_str is not a valid document type
    """
    if type_str not in ALL_DOCUMENT_TYPES:
        raise ValueError(
            f"Invalid document type: '{type_str}'. "
            f"Valid types: {', '.join(ALL_DOCUMENT_TYPES)}"
        )
    return type_str  # type: ignore


def is_valid_document_type(type_str: str) -> bool:
    """Check if a string is a valid document type."""
    return type_str in ALL_DOCUMENT_TYPES


def get_type_category(doc_type: str) -> TypeCategory | None:
    """Get the category for a document type."""
    return TYPE_CATEGORIES.get(doc_type)  # type: ignore
