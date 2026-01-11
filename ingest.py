"""
Cortex Ingestion Engine

Handles:
- File walking with gitignore-style patterns
- Git-based delta sync (with MD5 fallback for non-git repos)
- AST-aware code chunking
- Contextual header generation via Claude Haiku
- Garbage collection for deleted/renamed files
"""

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

import chromadb
from anthropic import Anthropic
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter
from tenacity import retry, stop_after_attempt, wait_exponential

from logging_config import get_logger
from rag_utils import DB_PATH, detect_language, get_current_branch, scrub_secrets

logger = get_logger("ingest")

# --- Configuration ---


def get_default_state_file() -> str:
    """Get the default state file path."""
    env_path = os.environ.get("CORTEX_STATE_FILE")
    if env_path:
        return os.path.expanduser(env_path)
    return os.path.join(DB_PATH, "ingest_state.json")


STATE_FILE = get_default_state_file()

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
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    return {}


def save_state(state: dict[str, Any], state_file: Optional[str] = None) -> None:
    """Save the ingestion state to disk atomically."""
    import shutil
    import tempfile

    path = state_file or STATE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Atomic write: write to temp file, then rename
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        shutil.move(tmp_path, path)  # Atomic on POSIX
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# --- Git Integration ---


def is_git_repo(path: str) -> bool:
    """Check if the given path is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_head_commit(path: str) -> Optional[str]:
    """Get the current HEAD commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def get_git_changed_files(
    path: str,
    since_commit: Optional[str],
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """
    Get files changed since a commit using git.

    Args:
        path: Repository root path
        since_commit: Commit to compare against (None = all files)

    Returns:
        Tuple of (modified_files, deleted_files, renamed_files)
        - modified_files: Files that were added or modified
        - deleted_files: Files that were deleted
        - renamed_files: List of (old_path, new_path) tuples
    """
    if not since_commit:
        return [], [], []

    try:
        # Get file status with rename detection
        result = subprocess.run(
            ["git", "diff", "--name-status", "-M", since_commit, "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(f"git diff failed: {result.stderr}")
            return [], [], []

        modified = []
        deleted = []
        renamed = []

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            parts = line.split("\t")
            status = parts[0]

            if status.startswith("R"):
                # Rename: R100\told_path\tnew_path
                if len(parts) >= 3:
                    old_path = os.path.join(path, parts[1])
                    new_path = os.path.join(path, parts[2])
                    renamed.append((old_path, new_path))
                    modified.append(new_path)  # Also index the new location
            elif status == "D":
                # Deleted
                deleted.append(os.path.join(path, parts[1]))
            elif status in ("A", "M", "T"):
                # Added, Modified, or Type changed
                modified.append(os.path.join(path, parts[1]))

        return modified, deleted, renamed

    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning(f"git command failed: {e}")
        return [], [], []


def get_untracked_files(path: str) -> list[str]:
    """Get untracked files that should be indexed."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return [
                os.path.join(path, f)
                for f in result.stdout.strip().split("\n")
                if f
            ]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return []


# --- Garbage Collection ---


def delete_file_chunks(
    collection: chromadb.Collection,
    file_paths: list[str],
    project_id: str,
) -> int:
    """
    Delete all chunks for the given file paths from ChromaDB.

    Args:
        collection: ChromaDB collection
        file_paths: List of file paths to delete chunks for
        project_id: Project identifier

    Returns:
        Number of chunks deleted
    """
    if not file_paths:
        return 0

    deleted_count = 0
    for file_path in file_paths:
        try:
            # Query for all chunks with this file path
            results = collection.get(
                where={
                    "$and": [
                        {"file_path": file_path},
                        {"project": project_id},
                    ]
                },
                include=[],  # We only need IDs
            )

            if results["ids"]:
                collection.delete(ids=results["ids"])
                deleted_count += len(results["ids"])
                logger.debug(f"Deleted {len(results['ids'])} chunks for: {file_path}")

        except Exception as e:
            logger.warning(f"Failed to delete chunks for {file_path}: {e}")

    return deleted_count


def cleanup_state_entries(
    state: dict[str, Any],
    deleted_files: list[str],
) -> None:
    """Remove deleted files from state's file_hashes."""
    file_hashes = state.get("file_hashes", {})
    for file_path in deleted_files:
        file_hashes.pop(file_path, None)


# --- Hash-based Fallback ---


def compute_file_hash(file_path: Path) -> str:
    """Compute MD5 hash of a file for delta sync (used as fallback)."""
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

# Header provider options: "anthropic", "claude-cli", "none"
HEADER_PROMPT_TEMPLATE = """Analyze this {language} code chunk from {file_path} and provide a brief (1-2 sentence) description of what it does. Focus on the purpose and key functionality.

Code:
```{language}
{chunk}
```

Respond with only the description, no formatting or prefixes."""


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=60),
    stop=stop_after_attempt(3),
)
def generate_header_with_anthropic(
    chunk: str,
    file_path: str,
    language: str,
    anthropic_client: Anthropic,
) -> str:
    """Generate a contextual header using the Anthropic API (Haiku)."""
    prompt = HEADER_PROMPT_TEMPLATE.format(
        language=language,
        file_path=file_path,
        chunk=chunk[:2000],
    )

    try:
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Anthropic API error: {e}")
        return f"Code snippet from {file_path}"


def generate_header_with_claude_cli(
    chunk: str,
    file_path: str,
    language: str,
) -> str:
    """Generate a contextual header using the Claude CLI."""
    import subprocess

    prompt = HEADER_PROMPT_TEMPLATE.format(
        language=language,
        file_path=file_path,
        chunk=chunk[:2000],
    )

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "haiku"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        logger.warning(f"Claude CLI error: {result.stderr}")
        return f"Code snippet from {file_path}"
    except FileNotFoundError:
        logger.warning("Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-cli")
        return f"Code snippet from {file_path}"
    except subprocess.TimeoutExpired:
        logger.warning("Claude CLI timed out")
        return f"Code snippet from {file_path}"
    except Exception as e:
        logger.warning(f"Claude CLI error: {e}")
        return f"Code snippet from {file_path}"


def generate_header_sync(
    chunk: str,
    file_path: str,
    language: Optional[Language],
    anthropic_client: Optional[Anthropic] = None,
    header_provider: str = "none",
) -> str:
    """
    Generate header for a chunk using the specified provider.

    Args:
        chunk: The code chunk
        file_path: Path to the source file
        language: Detected language
        anthropic_client: Anthropic client (for "anthropic" provider)
        header_provider: One of "anthropic", "claude-cli", or "none"
    """
    lang_str = language.value if language else "text"

    if header_provider == "anthropic" and anthropic_client:
        return generate_header_with_anthropic(chunk, file_path, lang_str, anthropic_client)
    elif header_provider == "claude-cli":
        return generate_header_with_claude_cli(chunk, file_path, lang_str)

    # Simple fallback header
    return f"Code from {file_path}"


# --- Main Ingestion ---


def ingest_file(
    file_path: Path,
    collection: chromadb.Collection,
    project_id: str,
    branch: str,
    anthropic_client: Optional[Anthropic] = None,
    header_provider: str = "none",
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> list[str]:
    """
    Ingest a single file into the collection.

    Args:
        file_path: Path to the file
        collection: ChromaDB collection
        project_id: Project identifier
        branch: Git branch name
        anthropic_client: Anthropic client (for "anthropic" header provider)
        header_provider: One of "anthropic", "claude-cli", or "none"
        chunk_size: Maximum chunk size
        chunk_overlap: Overlap between chunks

    Returns list of document IDs created.
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, IOError) as e:
        logger.debug(f"Skipped (read error): {file_path} - {e}")
        return []

    if not content.strip():
        logger.debug(f"Skipped (empty): {file_path}")
        return []

    # Detect language and scrub secrets
    language = detect_language(str(file_path), content)
    content = scrub_secrets(content)

    # Chunk the content
    chunks = chunk_code_file(content, language, chunk_size, chunk_overlap)

    if not chunks:
        logger.debug(f"Skipped (no chunks): {file_path}")
        return []

    doc_ids = []
    path_str = str(file_path)
    lang_str = language.value if language else "unknown"

    for i, chunk in enumerate(chunks):
        # Generate contextual header
        header = generate_header_sync(
            chunk,
            path_str,
            language,
            anthropic_client,
            header_provider=header_provider,
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
                    "language": lang_str,
                    "type": "code",
                }
            ],
        )
        doc_ids.append(doc_id)

    logger.debug(f"File: {file_path.name} -> {len(chunks)} chunks ({lang_str})")
    return doc_ids


def ingest_codebase(
    root_path: str,
    collection: chromadb.Collection,
    project_id: Optional[str] = None,
    anthropic_client: Optional[Anthropic] = None,
    force_full: bool = False,
    header_provider: str = "none",
    state_file: Optional[str] = None,
) -> dict[str, Any]:
    """
    Ingest an entire codebase into the collection.

    Uses git-based delta sync when available:
    - Only processes files changed since last indexed commit
    - Garbage collects chunks for deleted files
    - Handles file renames (deletes old path, indexes new path)

    Falls back to MD5 hash-based delta sync for non-git repos.

    Args:
        root_path: Root directory to ingest
        collection: ChromaDB collection to add documents to
        project_id: Project identifier (defaults to directory name)
        anthropic_client: Anthropic client (for "anthropic" header provider)
        force_full: Force full re-ingestion (ignore delta sync)
        header_provider: One of "anthropic", "claude-cli", or "none"
        state_file: Path to state file for delta sync

    Returns:
        Stats about the ingestion
    """
    start_time = time.time()
    root = Path(root_path)
    project_id = project_id or root.name
    branch = get_current_branch(root_path)

    logger.info(f"Starting ingestion: {root_path} (project={project_id}, branch={branch})")

    stats = {
        "project": project_id,
        "branch": branch,
        "files_scanned": 0,
        "files_processed": 0,
        "files_skipped": 0,
        "files_deleted": 0,
        "chunks_created": 0,
        "chunks_deleted": 0,
        "delta_mode": "full",  # Will be updated to "git" or "hash"
        "errors": [],
    }

    # Load state for delta sync
    raw_state = {} if force_full else load_state(state_file)

    # Migrate old state format (flat dict of path->hash) to new format
    if raw_state and "indexed_commit" not in raw_state and "file_hashes" not in raw_state:
        # Old format: {"path1": "hash1", "path2": "hash2"}
        # New format: {"indexed_commit": "...", "indexed_at": "...", "file_hashes": {...}}
        state = {
            "file_hashes": raw_state,
            "indexed_commit": None,
            "indexed_at": None,
        }
    else:
        state = raw_state if raw_state else {
            "file_hashes": {},
            "indexed_commit": None,
            "indexed_at": None,
        }

    # Determine delta sync strategy
    use_git = is_git_repo(root_path) and not force_full
    last_commit = state.get("indexed_commit") if use_git else None
    current_commit = get_head_commit(root_path) if use_git else None

    files_to_process: list[Path] = []
    deleted_files: list[str] = []
    renamed_files: list[tuple[str, str]] = []

    if force_full:
        # Full re-ingestion requested
        stats["delta_mode"] = "full"
        all_files = list(walk_codebase(root_path))
        files_to_process = all_files
        stats["files_scanned"] = len(all_files)
        logger.info(f"Full ingestion: {len(all_files)} files")

    elif use_git and last_commit and current_commit:
        # Git-based delta sync (fast path)
        stats["delta_mode"] = "git"
        modified, deleted_files, renamed_files = get_git_changed_files(
            root_path, last_commit
        )

        # Also check for untracked files
        untracked = get_untracked_files(root_path)

        # Combine modified and untracked, filter through walk_codebase patterns
        all_changed = set(modified + untracked)
        all_valid_files = set(str(f) for f in walk_codebase(root_path))

        # Only process files that pass our filters (not binary, not ignored, etc.)
        files_to_process = [
            Path(f) for f in all_changed
            if f in all_valid_files and Path(f).exists()
        ]

        stats["files_scanned"] = len(files_to_process)
        logger.info(
            f"Git delta sync: {len(files_to_process)} modified, "
            f"{len(deleted_files)} deleted, {len(renamed_files)} renamed"
        )

    else:
        # Hash-based fallback (first index or non-git repo)
        stats["delta_mode"] = "hash" if not force_full else "full"
        all_files = list(walk_codebase(root_path))
        stats["files_scanned"] = len(all_files)

        # Filter to changed files using MD5 hashes
        file_hashes = state.get("file_hashes", {})
        files_to_process = get_changed_files(all_files, file_hashes)

        skipped_unchanged = len(all_files) - len(files_to_process)
        if skipped_unchanged > 0:
            logger.debug(f"Skipped (unchanged by hash): {skipped_unchanged} files")

    # --- Garbage Collection ---
    # Handle deleted files: remove their chunks from ChromaDB
    if deleted_files:
        chunks_deleted = delete_file_chunks(collection, deleted_files, project_id)
        stats["files_deleted"] = len(deleted_files)
        stats["chunks_deleted"] = chunks_deleted
        cleanup_state_entries(state, deleted_files)
        logger.info(f"Garbage collected: {len(deleted_files)} files, {chunks_deleted} chunks")

    # Handle renamed files: delete chunks at old paths
    if renamed_files:
        old_paths = [old for old, new in renamed_files]
        chunks_deleted = delete_file_chunks(collection, old_paths, project_id)
        stats["chunks_deleted"] += chunks_deleted
        cleanup_state_entries(state, old_paths)
        logger.info(f"Cleaned up {len(renamed_files)} renamed files")

    # --- Process Files ---
    file_hashes = state.get("file_hashes", {})

    for file_path in files_to_process:
        try:
            doc_ids = ingest_file(
                file_path=file_path,
                collection=collection,
                project_id=project_id,
                branch=branch,
                anthropic_client=anthropic_client,
                header_provider=header_provider,
            )

            if doc_ids:
                stats["files_processed"] += 1
                stats["chunks_created"] += len(doc_ids)

                # Update state with new hash (for fallback mode and integrity)
                file_hashes[str(file_path)] = compute_file_hash(file_path)
            else:
                stats["files_skipped"] += 1

        except Exception as e:
            logger.warning(f"Error processing {file_path}: {e}")
            stats["errors"].append({"file": str(file_path), "error": str(e)})
            stats["files_skipped"] += 1

    # Update state with current commit and timestamp
    state["file_hashes"] = file_hashes
    state["indexed_commit"] = current_commit
    state["indexed_at"] = datetime.now(timezone.utc).isoformat()
    state["project"] = project_id
    state["branch"] = branch

    # Save updated state
    save_state(state, state_file)

    # Generate and store skeleton
    try:
        tree_output, tree_stats = generate_tree_structure(root_path)
        store_skeleton(collection, tree_output, project_id, branch, tree_stats)
        stats["skeleton"] = tree_stats
        logger.info(f"Skeleton indexed: {tree_stats['total_files']} files, {tree_stats['total_dirs']} dirs")
    except Exception as e:
        logger.warning(f"Skeleton generation failed: {e}")
        stats["skeleton"] = {"error": str(e)}

    elapsed = time.time() - start_time
    logger.info(
        f"Ingestion complete ({stats['delta_mode']}): "
        f"{stats['files_processed']} files, {stats['chunks_created']} chunks, "
        f"{stats['chunks_deleted']} deleted in {elapsed:.1f}s"
    )

    return stats


# --- Skeleton Index ---


def generate_tree_structure(
    root_path: str,
    max_depth: int = 10,
    ignore_patterns: Optional[set[str]] = None,
) -> tuple[str, dict]:
    """
    Generate tree output for a project directory.

    Tries system `tree` command first, falls back to Python implementation.

    Args:
        root_path: Root directory path
        max_depth: Maximum depth to traverse
        ignore_patterns: Patterns to ignore (uses DEFAULT_IGNORE_PATTERNS if None)

    Returns:
        (tree_text, stats_dict)
    """
    import subprocess

    root = Path(root_path)
    ignore = ignore_patterns or DEFAULT_IGNORE_PATTERNS

    # Try system 'tree' command first
    try:
        ignore_pattern = "|".join(ignore)
        result = subprocess.run(
            ["tree", "-L", str(max_depth), "-a", "-I", ignore_pattern, "--noreport"],
            cwd=root_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            tree_output = result.stdout.strip()
        else:
            tree_output = _generate_tree_fallback(root, max_depth, ignore)
    except FileNotFoundError:
        # 'tree' command not installed
        tree_output = _generate_tree_fallback(root, max_depth, ignore)
    except subprocess.TimeoutExpired:
        tree_output = _generate_tree_fallback(root, max_depth, ignore)

    # Calculate stats
    stats = _analyze_tree(tree_output)

    return tree_output, stats


def _generate_tree_fallback(
    root: Path,
    max_depth: int,
    ignore: set[str],
) -> str:
    """Pure-Python tree generation fallback."""

    def traverse(path: Path, prefix: str = "", depth: int = 0) -> list[str]:
        if depth > max_depth:
            return []

        lines = []
        try:
            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            # Filter ignored items
            items = [
                i
                for i in items
                if i.name not in ignore
                and not i.name.startswith(".")
                and not i.name.endswith(".egg-info")
            ]

            for i, item in enumerate(items):
                is_last = i == len(items) - 1
                current_prefix = "└── " if is_last else "├── "
                lines.append(f"{prefix}{current_prefix}{item.name}")

                if item.is_dir():
                    next_prefix = prefix + ("    " if is_last else "│   ")
                    lines.extend(traverse(item, next_prefix, depth + 1))
        except PermissionError:
            pass

        return lines

    tree_lines = [root.name]
    tree_lines.extend(traverse(root))
    return "\n".join(tree_lines)


def _analyze_tree(tree_output: str) -> dict:
    """Extract stats from tree output."""
    lines = tree_output.split("\n")
    file_count = 0
    dir_count = 0

    for line in lines[1:]:  # Skip root
        # Count entries (lines with tree connectors)
        if "├── " in line or "└── " in line:
            # Directories typically don't have extensions or end with /
            name = line.split("── ")[-1] if "── " in line else ""
            if "." in name and not name.endswith("/"):
                file_count += 1
            else:
                dir_count += 1

    return {
        "total_lines": len(lines),
        "total_files": file_count,
        "total_dirs": dir_count,
    }


def store_skeleton(
    collection: chromadb.Collection,
    tree_output: str,
    project_id: str,
    branch: str,
    stats: dict,
) -> str:
    """
    Store skeleton in collection with type='skeleton' metadata.

    Args:
        collection: ChromaDB collection
        tree_output: The tree structure text
        project_id: Project identifier
        branch: Git branch name
        stats: Tree statistics

    Returns:
        Document ID
    """
    from datetime import datetime, timezone

    doc_id = f"{project_id}:skeleton:{branch}"

    collection.upsert(
        ids=[doc_id],
        documents=[tree_output],
        metadatas=[
            {
                "type": "skeleton",
                "project": project_id,
                "branch": branch,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_files": stats.get("total_files", 0),
                "total_dirs": stats.get("total_dirs", 0),
            }
        ],
    )

    logger.debug(f"Skeleton stored: {doc_id} ({stats['total_files']} files, {stats['total_dirs']} dirs)")
    return doc_id


def ingest_files(
    file_paths: list[str],
    collection: chromadb.Collection,
    project_id: str,
    anthropic_client: Optional[Anthropic] = None,
    header_provider: str = "none",
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
                header_provider=header_provider,
            )

            stats["files_processed"] += 1
            stats["chunks_added"] += len(doc_ids)

        except Exception as e:
            stats["errors"].append({"file": path_str, "error": str(e)})

    return stats
