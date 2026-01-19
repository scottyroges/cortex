"""
AST-Based Code Analysis

Tree-sitter based extraction of metadata from source code files.
Replaces raw code chunking with structured metadata that helps
AI agents find WHERE to look, not WHAT the code says.

Philosophy: "Code can be grepped. Understanding cannot."
"""

from src.ast.models import (
    ClassInfo,
    DataContractInfo,
    FieldInfo,
    FileMetadata,
    FunctionSignature,
    ImportInfo,
    ParameterInfo,
)
from src.ast.parser import ASTParser, get_parser
from src.ast.description import (
    generate_description,
    generate_description_from_metadata,
    generate_descriptions_batch,
)

__all__ = [
    # Models
    "FileMetadata",
    "ImportInfo",
    "ClassInfo",
    "FunctionSignature",
    "DataContractInfo",
    "FieldInfo",
    "ParameterInfo",
    # Parser
    "ASTParser",
    "get_parser",
    # Description generation
    "generate_description",
    "generate_description_from_metadata",
    "generate_descriptions_batch",
]
