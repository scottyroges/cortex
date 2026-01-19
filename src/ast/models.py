"""
Data Models for AST Extraction

Structured representations of code metadata extracted from source files.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ImportInfo:
    """Represents an import statement."""

    module: str  # The imported module/package
    names: list[str] = field(default_factory=list)  # Specific imports (empty = whole module)
    alias: Optional[str] = None  # Import alias (as X)
    is_external: bool = True  # External package vs internal module


@dataclass
class ParameterInfo:
    """Represents a function parameter."""

    name: str
    type_annotation: Optional[str] = None
    default_value: Optional[str] = None
    is_optional: bool = False


@dataclass
class FunctionSignature:
    """Represents a function or method signature."""

    name: str
    parameters: list[ParameterInfo] = field(default_factory=list)
    return_type: Optional[str] = None
    is_async: bool = False
    is_method: bool = False  # True if defined inside a class
    decorators: list[str] = field(default_factory=list)
    docstring: Optional[str] = None


@dataclass
class ClassInfo:
    """Represents a class definition."""

    name: str
    bases: list[str] = field(default_factory=list)  # Parent classes
    methods: list[FunctionSignature] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    docstring: Optional[str] = None
    is_dataclass: bool = False
    is_pydantic: bool = False


@dataclass
class FieldInfo:
    """Represents a field in a data contract."""

    name: str
    type_annotation: str
    optional: bool = False
    default_value: Optional[str] = None


@dataclass
class DataContractInfo:
    """Represents a data contract (interface, type, schema, DTO)."""

    name: str
    contract_type: str  # interface, type, schema, model, dto, dataclass
    fields: list[FieldInfo] = field(default_factory=list)
    source_text: Optional[str] = None  # Original source for embedding


@dataclass
class FileMetadata:
    """Complete metadata for a source file."""

    file_path: str
    language: str

    # LLM-generated (mandatory for good search)
    description: str = ""

    # AST-extracted
    imports: list[ImportInfo] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)  # Exported symbol names
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionSignature] = field(default_factory=list)
    data_contracts: list[DataContractInfo] = field(default_factory=list)

    # Classification flags
    is_entry_point: bool = False
    entry_point_type: Optional[str] = None  # main, api_route, cli, event_handler
    is_barrel: bool = False  # Re-export file (index.ts, __init__.py)
    is_test: bool = False
    is_config: bool = False

    # Staleness tracking
    file_hash: Optional[str] = None

    def get_export_list(self) -> list[str]:
        """Get all exported symbols (classes, functions, explicit exports)."""
        symbols = list(self.exports)
        symbols.extend(c.name for c in self.classes)
        symbols.extend(f.name for f in self.functions if not f.is_method)
        return list(set(symbols))

    def to_search_content(self) -> str:
        """Generate searchable content for vector embedding."""
        parts = [self.file_path]

        if self.description:
            parts.append(self.description)

        if self.exports:
            parts.append(f"Exports: {', '.join(self.exports[:10])}")

        if self.imports:
            import_names = [i.module for i in self.imports[:10]]
            parts.append(f"Imports: {', '.join(import_names)}")

        return "\n\n".join(parts)
