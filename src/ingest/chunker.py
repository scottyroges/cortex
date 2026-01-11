"""
AST-Aware Code Chunking

Language detection and code-aware text splitting.
"""

import re
from pathlib import Path
from typing import Optional

from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

# --- Language Detection ---

EXTENSION_TO_LANGUAGE: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".js": Language.JS,
    ".jsx": Language.JS,
    ".ts": Language.TS,
    ".tsx": Language.TS,
    ".java": Language.JAVA,
    ".go": Language.GO,
    ".rs": Language.RUST,
    ".rb": Language.RUBY,
    ".php": Language.PHP,
    ".cpp": Language.CPP,
    ".cc": Language.CPP,
    ".cxx": Language.CPP,
    ".c": Language.C,
    ".h": Language.C,
    ".hpp": Language.CPP,
    ".cs": Language.CSHARP,
    ".swift": Language.SWIFT,
    ".kt": Language.KOTLIN,
    ".kts": Language.KOTLIN,
    ".scala": Language.SCALA,
    ".md": Language.MARKDOWN,
    ".markdown": Language.MARKDOWN,
    ".html": Language.HTML,
    ".htm": Language.HTML,
    ".sol": Language.SOL,
    ".lua": Language.LUA,
    ".hs": Language.HASKELL,
    ".ex": Language.ELIXIR,
    ".exs": Language.ELIXIR,
}


def detect_language(file_path: str, content: Optional[str] = None) -> Optional[Language]:
    """
    Detect programming language from file extension or shebang.

    Args:
        file_path: Path to the file
        content: Optional file content for shebang detection

    Returns:
        Language enum or None if not detected
    """
    # Check extension first
    ext = Path(file_path).suffix.lower()
    lang = EXTENSION_TO_LANGUAGE.get(ext)

    # If no match and content provided, check shebang
    if not lang and content and content.startswith("#!"):
        first_line = content.split("\n")[0].lower()
        if "python" in first_line:
            return Language.PYTHON
        if "node" in first_line or "deno" in first_line:
            return Language.JS
        if "ruby" in first_line:
            return Language.RUBY
        if "bash" in first_line or "sh" in first_line:
            return None  # Shell scripts don't have good AST support

    return lang


# --- Scope Extraction ---


def extract_scope_from_chunk(chunk: str, language: Optional[Language]) -> dict:
    """
    Extract function/class names from a code chunk.

    Uses regex patterns to identify the containing scope without full AST parsing.
    Returns the innermost scope found in the chunk.

    Args:
        chunk: The code chunk text
        language: Detected language (for language-specific patterns)

    Returns:
        Dict with function_name, class_name, and scope (full path)
    """
    result = {
        "function_name": None,
        "class_name": None,
        "scope": None,
    }

    if not chunk or not language:
        return result

    # Language-specific patterns
    patterns = {
        # Python: def func_name, class ClassName, async def func_name
        Language.PYTHON: {
            "function": r"(?:async\s+)?def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
            "class": r"class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[:\(]",
        },
        # JavaScript/TypeScript: function name, const name =, class Name
        Language.JS: {
            "function": r"(?:function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)|(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*(?:async\s*)?\()",
            "class": r"class\s+([a-zA-Z_$][a-zA-Z0-9_$]*)",
        },
        Language.TS: {
            "function": r"(?:function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)|(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*(?:async\s*)?\()",
            "class": r"class\s+([a-zA-Z_$][a-zA-Z0-9_$]*)",
        },
        # Go: func name, func (receiver) name, type Name struct
        Language.GO: {
            "function": r"func\s+(?:\([^)]+\)\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
            "class": r"type\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+struct",
        },
        # Rust: fn name, impl Name, struct Name
        Language.RUST: {
            "function": r"(?:pub\s+)?(?:async\s+)?fn\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            "class": r"(?:pub\s+)?(?:struct|impl|enum)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        },
        # Java/Kotlin: class Name, void/type methodName
        Language.JAVA: {
            "function": r"(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
            "class": r"(?:public\s+)?(?:abstract\s+)?(?:final\s+)?class\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        },
        Language.KOTLIN: {
            "function": r"(?:fun|suspend\s+fun)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            "class": r"(?:class|object|interface)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        },
        # Ruby: def method_name, class ClassName
        Language.RUBY: {
            "function": r"def\s+(?:self\.)?([a-zA-Z_][a-zA-Z0-9_?!]*)",
            "class": r"(?:class|module)\s+([A-Z][a-zA-Z0-9_]*)",
        },
        # C/C++: return_type function_name, class Name
        Language.C: {
            "function": r"(?:[\w*]+\s+)+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^;]*\)\s*{",
            "class": r"(?:struct|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        },
        Language.CPP: {
            "function": r"(?:[\w*:]+\s+)*([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^;]*\)\s*(?:const\s*)?(?:override\s*)?{",
            "class": r"(?:struct|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        },
    }

    # Get patterns for this language (fallback to Python-like patterns)
    lang_patterns = patterns.get(language, patterns.get(Language.PYTHON, {}))

    # Find all classes in the chunk (take the first/outermost one)
    class_pattern = lang_patterns.get("class")
    if class_pattern:
        class_matches = re.findall(class_pattern, chunk)
        if class_matches:
            # Take the first match (outermost class)
            match = class_matches[0]
            result["class_name"] = match if isinstance(match, str) else match[0] if match else None

    # Find all functions in the chunk (take the last/innermost one)
    func_pattern = lang_patterns.get("function")
    if func_pattern:
        func_matches = re.findall(func_pattern, chunk)
        if func_matches:
            # Take the last match (innermost function, most specific)
            match = func_matches[-1]
            # Handle tuple results from multiple capture groups
            if isinstance(match, tuple):
                result["function_name"] = next((m for m in match if m), None)
            else:
                result["function_name"] = match

    # Build full scope path
    scope_parts = []
    if result["class_name"]:
        scope_parts.append(result["class_name"])
    if result["function_name"]:
        scope_parts.append(result["function_name"])

    if scope_parts:
        result["scope"] = ".".join(scope_parts)

    return result


# --- Code Chunking ---


def chunk_code_file(
    content: str,
    language: Optional[Language],
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> list[str]:
    """
    Chunk code using language-aware splitter.

    Falls back to generic splitting if language not supported.

    Args:
        content: File content to chunk
        language: Detected programming language
        chunk_size: Maximum chunk size in characters
        chunk_overlap: Overlap between chunks

    Returns:
        List of text chunks
    """
    if language:
        try:
            splitter = RecursiveCharacterTextSplitter.from_language(
                language=language,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            return splitter.split_text(content)
        except ValueError:
            # Language not supported by splitter
            pass

    # Fallback: Use generic splitter with code-friendly separators
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", " ", ""],
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return splitter.split_text(content)
