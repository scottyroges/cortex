"""
Tree-sitter Parser Wrapper

Handles language detection and tree-sitter parsing for multiple languages.
"""

from pathlib import Path
from typing import Optional

import tree_sitter_python
import tree_sitter_typescript
import tree_sitter_kotlin
from tree_sitter import Language, Parser, Tree

from logging_config import get_logger

logger = get_logger("ast.parser")


# Supported languages and their tree-sitter modules
LANGUAGE_MODULES = {
    "python": tree_sitter_python,
    "typescript": tree_sitter_typescript.language_typescript,
    "tsx": tree_sitter_typescript.language_tsx,
    "kotlin": tree_sitter_kotlin,
}

# File extension to language mapping
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".pyw": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "typescript",  # Use TS parser for JS (superset)
    ".jsx": "tsx",
    ".mjs": "typescript",
    ".cjs": "typescript",
    ".kt": "kotlin",
    ".kts": "kotlin",
}


class ASTParser:
    """
    Tree-sitter based parser for multiple languages.

    Lazily initializes parsers for each language on first use.
    """

    def __init__(self):
        self._parsers: dict[str, Parser] = {}
        self._languages: dict[str, Language] = {}

    def _get_language(self, lang_name: str) -> Optional[Language]:
        """Get or create Language object for a language."""
        if lang_name in self._languages:
            return self._languages[lang_name]

        module = LANGUAGE_MODULES.get(lang_name)
        if module is None:
            logger.warning(f"Unsupported language: {lang_name}")
            return None

        try:
            # Handle both module and function-style language getters
            if callable(module):
                language = Language(module())
            else:
                language = Language(module.language())
            self._languages[lang_name] = language
            return language
        except Exception as e:
            logger.error(f"Failed to load language {lang_name}: {e}")
            return None

    def _get_parser(self, lang_name: str) -> Optional[Parser]:
        """Get or create Parser for a language."""
        if lang_name in self._parsers:
            return self._parsers[lang_name]

        language = self._get_language(lang_name)
        if language is None:
            return None

        parser = Parser(language)
        self._parsers[lang_name] = parser
        return parser

    def detect_language(self, file_path: str) -> Optional[str]:
        """
        Detect language from file extension.

        Args:
            file_path: Path to the source file

        Returns:
            Language name or None if unsupported
        """
        ext = Path(file_path).suffix.lower()
        return EXTENSION_TO_LANGUAGE.get(ext)

    def parse(self, source: str, language: str) -> Optional[Tree]:
        """
        Parse source code into an AST.

        Args:
            source: Source code as string
            language: Language name (python, typescript, kotlin)

        Returns:
            Tree-sitter Tree or None if parsing failed
        """
        parser = self._get_parser(language)
        if parser is None:
            return None

        try:
            return parser.parse(source.encode("utf-8"))
        except Exception as e:
            logger.error(f"Failed to parse {language} code: {e}")
            return None

    def parse_file(self, file_path: str) -> tuple[Optional[Tree], Optional[str]]:
        """
        Parse a file into an AST.

        Args:
            file_path: Path to the source file

        Returns:
            Tuple of (Tree, language) or (None, None) if failed
        """
        language = self.detect_language(file_path)
        if language is None:
            return None, None

        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        except (OSError, IOError) as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            return None, None

        tree = self.parse(content, language)
        return tree, language

    def is_supported(self, file_path: str) -> bool:
        """Check if a file's language is supported."""
        return self.detect_language(file_path) is not None


# Global parser instance (lazy singleton)
_parser: Optional[ASTParser] = None


def get_parser() -> ASTParser:
    """Get the global ASTParser instance."""
    global _parser
    if _parser is None:
        _parser = ASTParser()
    return _parser
