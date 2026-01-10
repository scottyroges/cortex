"""
Cortex Ingestion Engine

Handles:
- File walking with gitignore-style patterns
- MD5 hash-based delta sync
- AST-aware code chunking
- Contextual header generation via Claude Haiku
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Generator, Optional

import chromadb
from anthropic import Anthropic
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter
from tenacity import retry, stop_after_attempt, wait_exponential

from rag_utils import detect_language, get_current_branch, scrub_secrets

# --- Configuration ---

STATE_FILE = os.environ.get("CORTEX_STATE_FILE", "/app/cortex_db/ingest_state.json")

DEFAULT_IGNORE_PATTERNS = {
    # Version control
    ".git",
    ".svn",
    ".hg",
    # Dependencies
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    # Build outputs
    "dist",
    "build",
    "out",
    ".next",
    ".nuxt",
    "target",
    # IDE
    ".idea",
    ".vscode",
    # Misc
    ".cache",
    "coverage",
    ".coverage",
    ".tox",
    ".eggs",
    "*.egg-info",
}

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

MAX_FILE_SIZE = 1_000_000  # 1MB max file size


# --- State Management ---


def load_state(state_file: Optional[str] = None) -> dict[str, str]:
    """Load the ingestion state (file hashes) from disk."""
    path = state_file or STATE_FILE
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def save_state(state: dict[str, str], state_file: Optional[str] = None) -> None:
    """Save the ingestion state to disk."""
    path = state_file or STATE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def compute_file_hash(file_path: Path) -> str:
    """Compute MD5 hash of a file for delta sync."""
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


# --- File Walking ---


def walk_codebase(
    root_path: str,
    extensions: Optional[set[str]] = None,
    ignore_patterns: Optional[set[str]] = None,
) -> Generator[Path, None, None]:
    """
    Walk codebase yielding files to process.

    Args:
        root_path: Root directory to walk
        extensions: Optional set of extensions to include (e.g., {'.py', '.js'})
        ignore_patterns: Patterns to ignore (directories/files)
    """
    ignore = ignore_patterns or DEFAULT_IGNORE_PATTERNS
    root = Path(root_path)

    for dirpath, dirnames, filenames in os.walk(root):
        # Filter out ignored directories (in-place modification)
        dirnames[:] = [
            d
            for d in dirnames
            if d not in ignore and not d.startswith(".") and not d.endswith(".egg-info")
        ]

        for filename in filenames:
            file_path = Path(dirpath) / filename

            # Skip hidden files
            if filename.startswith("."):
                continue

            # Skip binary/large files
            if file_path.suffix.lower() in BINARY_EXTENSIONS:
                continue

            # Check file size
            try:
                if file_path.stat().st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            # Filter by extension if specified
            if extensions and file_path.suffix.lower() not in extensions:
                continue

            yield file_path


def get_changed_files(
    file_paths: list[Path],
    state: dict[str, str],
) -> list[Path]:
    """Return only files that have changed since last ingestion."""
    changed = []

    for file_path in file_paths:
        path_str = str(file_path)
        try:
            current_hash = compute_file_hash(file_path)
            if state.get(path_str) != current_hash:
                changed.append(file_path)
        except (OSError, IOError):
            # If we can't read the file, skip it
            continue

    return changed


# --- AST Chunking ---


def chunk_code_file(
    content: str,
    language: Optional[Language],
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> list[str]:
    """
    Chunk code using language-aware splitter.

    Falls back to generic splitting if language not supported.
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


# --- Contextual Headers ---


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=60),
    stop=stop_after_attempt(3),
)
def generate_contextual_header(
    chunk: str,
    file_path: str,
    language: str,
    anthropic_client: Anthropic,
) -> str:
    """
    Generate a contextual header using Claude Haiku.

    Describes what the code chunk does in 1-2 sentences.
    """
    prompt = f"""Analyze this {language} code chunk from {file_path} and provide a brief (1-2 sentence) description of what it does. Focus on the purpose and key functionality.

Code:
```{language}
{chunk[:2000]}
```

Respond with only the description, no formatting or prefixes."""

    try:
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        # Fallback to basic header
        return f"Code snippet from {file_path}"


def generate_header_sync(
    chunk: str,
    file_path: str,
    language: Optional[Language],
    anthropic_client: Optional[Anthropic],
    use_haiku: bool = True,
) -> str:
    """
    Generate header for a chunk, optionally using Haiku.

    Args:
        chunk: The code chunk
        file_path: Path to the source file
        language: Detected language
        anthropic_client: Anthropic client (optional)
        use_haiku: Whether to use Haiku for header generation
    """
    lang_str = language.value if language else "text"

    if use_haiku and anthropic_client:
        return generate_contextual_header(chunk, file_path, lang_str, anthropic_client)

    # Simple fallback header
    return f"Code from {file_path}"


# --- Main Ingestion ---


def ingest_file(
    file_path: Path,
    collection: chromadb.Collection,
    project_id: str,
    branch: str,
    anthropic_client: Optional[Anthropic] = None,
    use_haiku: bool = True,
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> list[str]:
    """
    Ingest a single file into the collection.

    Returns list of document IDs created.
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, IOError):
        return []

    if not content.strip():
        return []

    # Detect language and scrub secrets
    language = detect_language(str(file_path), content)
    content = scrub_secrets(content)

    # Chunk the content
    chunks = chunk_code_file(content, language, chunk_size, chunk_overlap)

    if not chunks:
        return []

    doc_ids = []
    path_str = str(file_path)

    for i, chunk in enumerate(chunks):
        # Generate contextual header
        header = generate_header_sync(
            chunk,
            path_str,
            language,
            anthropic_client,
            use_haiku=use_haiku,
        )

        # Combine header with chunk
        full_text = f"{header}\n\n---\n\n{chunk}"

        # Create document ID
        doc_id = f"{project_id}:{path_str}:{i}"

        # Upsert to collection
        collection.upsert(
            ids=[doc_id],
            documents=[full_text],
            metadatas=[
                {
                    "file_path": path_str,
                    "project": project_id,
                    "branch": branch,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "language": language.value if language else "unknown",
                    "type": "code",
                }
            ],
        )
        doc_ids.append(doc_id)

    return doc_ids


def ingest_codebase(
    root_path: str,
    collection: chromadb.Collection,
    project_id: Optional[str] = None,
    anthropic_client: Optional[Anthropic] = None,
    force_full: bool = False,
    use_haiku: bool = True,
    state_file: Optional[str] = None,
) -> dict[str, Any]:
    """
    Ingest an entire codebase into the collection.

    Args:
        root_path: Root directory to ingest
        collection: ChromaDB collection to add documents to
        project_id: Project identifier (defaults to directory name)
        anthropic_client: Anthropic client for Haiku headers
        force_full: Force full re-ingestion (ignore delta sync)
        use_haiku: Use Haiku for contextual headers
        state_file: Path to state file for delta sync

    Returns:
        Stats about the ingestion
    """
    root = Path(root_path)
    project_id = project_id or root.name
    branch = get_current_branch(root_path)

    stats = {
        "project": project_id,
        "branch": branch,
        "files_scanned": 0,
        "files_processed": 0,
        "files_skipped": 0,
        "chunks_added": 0,
        "errors": [],
    }

    # Load state for delta sync
    state = {} if force_full else load_state(state_file)

    # Walk codebase
    all_files = list(walk_codebase(root_path))
    stats["files_scanned"] = len(all_files)

    # Filter to changed files
    files_to_process = all_files if force_full else get_changed_files(all_files, state)

    for file_path in files_to_process:
        try:
            doc_ids = ingest_file(
                file_path=file_path,
                collection=collection,
                project_id=project_id,
                branch=branch,
                anthropic_client=anthropic_client,
                use_haiku=use_haiku,
            )

            if doc_ids:
                stats["files_processed"] += 1
                stats["chunks_added"] += len(doc_ids)

                # Update state with new hash
                state[str(file_path)] = compute_file_hash(file_path)
            else:
                stats["files_skipped"] += 1

        except Exception as e:
            stats["errors"].append({"file": str(file_path), "error": str(e)})
            stats["files_skipped"] += 1

    # Save updated state
    save_state(state, state_file)

    return stats


def ingest_files(
    file_paths: list[str],
    collection: chromadb.Collection,
    project_id: str,
    anthropic_client: Optional[Anthropic] = None,
    use_haiku: bool = True,
) -> dict[str, Any]:
    """
    Ingest specific files into the collection.

    Used by smart_commit to re-index only changed files.
    """
    # Get branch from first file's directory
    if file_paths:
        first_path = Path(file_paths[0])
        branch = get_current_branch(str(first_path.parent))
    else:
        branch = "unknown"

    stats = {
        "files_processed": 0,
        "chunks_added": 0,
        "errors": [],
    }

    for path_str in file_paths:
        file_path = Path(path_str)

        if not file_path.exists():
            stats["errors"].append({"file": path_str, "error": "File not found"})
            continue

        try:
            doc_ids = ingest_file(
                file_path=file_path,
                collection=collection,
                project_id=project_id,
                branch=branch,
                anthropic_client=anthropic_client,
                use_haiku=use_haiku,
            )

            stats["files_processed"] += 1
            stats["chunks_added"] += len(doc_ids)

        except Exception as e:
            stats["errors"].append({"file": path_str, "error": str(e)})

    return stats
