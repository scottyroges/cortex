"""
Base Extractor Interface

Abstract base class that all language extractors must implement.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from tree_sitter import Node, Tree

from src.ast.models import (
    ClassInfo,
    DataContractInfo,
    FileMetadata,
    FunctionSignature,
    ImportInfo,
)


class LanguageExtractor(ABC):
    """
    Abstract base class for language-specific AST extractors.

    Each language (Python, TypeScript, Kotlin) implements this interface
    to extract structured metadata from source code.
    """

    @property
    @abstractmethod
    def language(self) -> str:
        """Return the language name (e.g., 'python', 'typescript')."""
        pass

    @abstractmethod
    def extract_imports(self, tree: Tree, source: str) -> list[ImportInfo]:
        """
        Extract import statements from the AST.

        Args:
            tree: Parsed AST tree
            source: Original source code

        Returns:
            List of ImportInfo objects
        """
        pass

    @abstractmethod
    def extract_exports(self, tree: Tree, source: str) -> list[str]:
        """
        Extract exported symbol names from the AST.

        For languages without explicit exports (Python), this returns
        module-level public symbols.

        Args:
            tree: Parsed AST tree
            source: Original source code

        Returns:
            List of exported symbol names
        """
        pass

    @abstractmethod
    def extract_classes(self, tree: Tree, source: str) -> list[ClassInfo]:
        """
        Extract class definitions from the AST.

        Args:
            tree: Parsed AST tree
            source: Original source code

        Returns:
            List of ClassInfo objects
        """
        pass

    @abstractmethod
    def extract_functions(self, tree: Tree, source: str) -> list[FunctionSignature]:
        """
        Extract top-level function definitions from the AST.

        Does not include methods (those are in ClassInfo.methods).

        Args:
            tree: Parsed AST tree
            source: Original source code

        Returns:
            List of FunctionSignature objects
        """
        pass

    @abstractmethod
    def extract_data_contracts(self, tree: Tree, source: str) -> list[DataContractInfo]:
        """
        Extract data contracts (interfaces, types, schemas) from the AST.

        Args:
            tree: Parsed AST tree
            source: Original source code

        Returns:
            List of DataContractInfo objects
        """
        pass

    @abstractmethod
    def detect_entry_point(self, tree: Tree, source: str, file_path: str) -> Optional[str]:
        """
        Detect if this file is an entry point and what type.

        Args:
            tree: Parsed AST tree
            source: Original source code
            file_path: Path to the file

        Returns:
            Entry point type (main, api_route, cli, etc.) or None
        """
        pass

    @abstractmethod
    def detect_barrel(self, tree: Tree, source: str, file_path: str) -> bool:
        """
        Detect if this file is a barrel file (re-exports only).

        Args:
            tree: Parsed AST tree
            source: Original source code
            file_path: Path to the file

        Returns:
            True if this is a barrel file
        """
        pass

    def extract_all(self, tree: Tree, source: str, file_path: str) -> FileMetadata:
        """
        Extract all metadata from a file.

        This is the main entry point that calls all extraction methods.

        Args:
            tree: Parsed AST tree
            source: Original source code
            file_path: Path to the file

        Returns:
            Complete FileMetadata object
        """
        path = Path(file_path)

        # Detect file classification
        is_test = self._is_test_file(file_path)
        is_config = self._is_config_file(file_path)
        entry_point_type = self.detect_entry_point(tree, source, file_path)
        is_barrel = self.detect_barrel(tree, source, file_path)

        return FileMetadata(
            file_path=file_path,
            language=self.language,
            imports=self.extract_imports(tree, source),
            exports=self.extract_exports(tree, source),
            classes=self.extract_classes(tree, source),
            functions=self.extract_functions(tree, source),
            data_contracts=self.extract_data_contracts(tree, source),
            is_entry_point=entry_point_type is not None,
            entry_point_type=entry_point_type,
            is_barrel=is_barrel,
            is_test=is_test,
            is_config=is_config,
        )

    def _is_test_file(self, file_path: str) -> bool:
        """Check if file is a test file based on path/name."""
        path = Path(file_path)
        name = path.name.lower()
        parts = [p.lower() for p in path.parts]

        # Common test patterns
        if name.startswith("test_") or name.endswith("_test.py"):
            return True
        if name.endswith(".test.ts") or name.endswith(".spec.ts"):
            return True
        if name.endswith(".test.js") or name.endswith(".spec.js"):
            return True
        if "tests" in parts or "test" in parts or "__tests__" in parts:
            return True

        return False

    def _is_config_file(self, file_path: str) -> bool:
        """Check if file is a configuration file."""
        path = Path(file_path)
        name = path.name.lower()

        config_names = {
            "config.py", "settings.py", "conf.py",
            "config.ts", "config.js",
            "tsconfig.json", "package.json", "pyproject.toml",
            ".env", ".env.example",
        }

        config_patterns = ["config", "settings", "conf"]

        if name in config_names:
            return True

        for pattern in config_patterns:
            if pattern in name:
                return True

        return False

    # Helper methods for AST traversal

    def get_node_text(self, node: Node, source: str) -> str:
        """Extract the text content of an AST node."""
        return source[node.start_byte:node.end_byte]

    def find_children(self, node: Node, type_name: str) -> list[Node]:
        """Find all direct children of a specific type."""
        return [child for child in node.children if child.type == type_name]

    def find_child(self, node: Node, type_name: str) -> Optional[Node]:
        """Find the first direct child of a specific type."""
        for child in node.children:
            if child.type == type_name:
                return child
        return None

    def walk_tree(self, node: Node, type_name: str) -> list[Node]:
        """
        Walk the tree and find all nodes of a specific type.

        Args:
            node: Starting node
            type_name: Node type to find

        Returns:
            List of matching nodes
        """
        results = []

        def _walk(n: Node):
            if n.type == type_name:
                results.append(n)
            for child in n.children:
                _walk(child)

        _walk(node)
        return results


# Registry of extractors by language
_extractors: dict[str, LanguageExtractor] = {}


def register_extractor(extractor: LanguageExtractor) -> None:
    """Register an extractor for a language."""
    _extractors[extractor.language] = extractor


def get_extractor(language: str) -> Optional[LanguageExtractor]:
    """
    Get the extractor for a language.

    Args:
        language: Language name (python, typescript, kotlin)

    Returns:
        LanguageExtractor or None if unsupported
    """
    return _extractors.get(language)
