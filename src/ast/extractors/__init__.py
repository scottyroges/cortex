"""
Language-Specific Extractors

Each extractor implements the LanguageExtractor interface for a specific language.
"""

from src.ast.extractors.base import LanguageExtractor, get_extractor, register_extractor

# Import extractors to trigger registration
from src.ast.extractors.python import PythonExtractor
from src.ast.extractors.typescript import TypeScriptExtractor
from src.ast.extractors.kotlin import KotlinExtractor

__all__ = [
    "LanguageExtractor",
    "get_extractor",
    "register_extractor",
    "PythonExtractor",
    "TypeScriptExtractor",
    "KotlinExtractor",
]
