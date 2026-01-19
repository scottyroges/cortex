"""
Tests for ingest module
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_text_splitters import Language

from src.config import DEFAULT_IGNORE_PATTERNS
from src.git import get_git_changed_files, get_head_commit, get_untracked_files, is_git_repo
from src.ingest import (
    chunk_code_file,
    compute_file_hash,
    extract_scope_from_chunk,
    generate_tree_structure,
    get_changed_files,
    ingest_codebase,
    ingest_file,
    store_skeleton,
    walk_codebase,
)
from src.ingest.skeleton import _analyze_tree, _generate_tree_fallback
from src.state import load_state, save_state
from src.storage import delete_file_chunks, get_or_create_collection
from src.storage.gc import cleanup_state_entries


class TestFileWalking:
    """Tests for file walking functionality."""

    def test_walk_basic(self, temp_dir: Path):
        """Test basic file walking."""
        # Create test files
        (temp_dir / "main.py").write_text("print('hello')")
        (temp_dir / "app.js").write_text("console.log('hi')")
        (temp_dir / "README.md").write_text("# Readme")

        files = list(walk_codebase(str(temp_dir)))
        assert len(files) == 3
        assert all(isinstance(f, Path) for f in files)

    def test_walk_ignores_node_modules(self, temp_dir: Path):
        """Test that node_modules is ignored."""
        (temp_dir / "main.py").write_text("print('hello')")

        nm_dir = temp_dir / "node_modules"
        nm_dir.mkdir()
        (nm_dir / "package.js").write_text("module.exports = {}")

        files = list(walk_codebase(str(temp_dir)))
        file_names = [f.name for f in files]
        assert "main.py" in file_names
        assert "package.js" not in file_names

    def test_walk_ignores_git(self, temp_dir: Path):
        """Test that .git directory is ignored."""
        (temp_dir / "main.py").write_text("print('hello')")

        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]")

        files = list(walk_codebase(str(temp_dir)))
        file_names = [f.name for f in files]
        assert "main.py" in file_names
        assert "config" not in file_names

    def test_walk_ignores_binary_files(self, temp_dir: Path):
        """Test that binary files are skipped."""
        (temp_dir / "main.py").write_text("print('hello')")
        (temp_dir / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        files = list(walk_codebase(str(temp_dir)))
        file_names = [f.name for f in files]
        assert "main.py" in file_names
        assert "image.png" not in file_names

    def test_walk_with_extension_filter(self, temp_dir: Path):
        """Test walking with extension filter."""
        (temp_dir / "main.py").write_text("print('hello')")
        (temp_dir / "app.js").write_text("console.log('hi')")
        (temp_dir / "style.css").write_text("body {}")

        files = list(walk_codebase(str(temp_dir), extensions={".py", ".js"}))
        file_names = [f.name for f in files]
        assert "main.py" in file_names
        assert "app.js" in file_names
        assert "style.css" not in file_names

    def test_walk_ignores_hidden_files(self, temp_dir: Path):
        """Test that hidden files are ignored."""
        (temp_dir / "main.py").write_text("print('hello')")
        (temp_dir / ".hidden").write_text("secret")
        (temp_dir / ".env").write_text("API_KEY=secret")

        files = list(walk_codebase(str(temp_dir)))
        file_names = [f.name for f in files]
        assert "main.py" in file_names
        assert ".hidden" not in file_names
        assert ".env" not in file_names

    def test_walk_nested_directories(self, temp_dir: Path):
        """Test walking nested directories."""
        src_dir = temp_dir / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("print('hello')")

        lib_dir = src_dir / "lib"
        lib_dir.mkdir()
        (lib_dir / "utils.py").write_text("def helper(): pass")

        files = list(walk_codebase(str(temp_dir)))
        file_names = [f.name for f in files]
        assert "main.py" in file_names
        assert "utils.py" in file_names


class TestDeltaSync:
    """Tests for delta sync functionality."""

    def test_compute_file_hash(self, sample_python_file: Path):
        """Test file hash computation."""
        hash1 = compute_file_hash(sample_python_file)
        assert len(hash1) == 32  # MD5 hex length

        # Same file should produce same hash
        hash2 = compute_file_hash(sample_python_file)
        assert hash1 == hash2

    def test_hash_changes_with_content(self, temp_dir: Path):
        """Test that hash changes when file content changes."""
        file_path = temp_dir / "test.py"
        file_path.write_text("version 1")
        hash1 = compute_file_hash(file_path)

        file_path.write_text("version 2")
        hash2 = compute_file_hash(file_path)

        assert hash1 != hash2

    def test_get_changed_files(self, temp_dir: Path):
        """Test detection of changed files."""
        file1 = temp_dir / "file1.py"
        file2 = temp_dir / "file2.py"
        file1.write_text("content 1")
        file2.write_text("content 2")

        # Initial state with file1's hash
        state = {str(file1): compute_file_hash(file1)}

        # file2 should be detected as changed (not in state)
        changed = get_changed_files([file1, file2], state)
        changed_names = [f.name for f in changed]
        assert "file2.py" in changed_names
        assert "file1.py" not in changed_names

    def test_state_persistence(self, temp_dir: Path):
        """Test state save and load."""
        state_file = temp_dir / "state.json"
        state = {"file1.py": "abc123", "file2.py": "def456"}

        save_state(state, str(state_file))
        loaded = load_state(str(state_file))

        assert loaded == state

    def test_load_missing_state(self, temp_dir: Path):
        """Test loading non-existent state file."""
        state_file = temp_dir / "nonexistent.json"
        loaded = load_state(str(state_file))
        assert loaded == {}


class TestChunking:
    """Tests for code chunking."""

    def test_chunk_python(self, sample_python_file: Path):
        """Test chunking Python code."""
        content = sample_python_file.read_text()
        chunks = chunk_code_file(content, Language.PYTHON)

        assert len(chunks) >= 1
        assert all(isinstance(c, str) for c in chunks)
        assert all(len(c) <= 1500 for c in chunks)  # Respects chunk_size

    def test_chunk_javascript(self, sample_js_file: Path):
        """Test chunking JavaScript code."""
        content = sample_js_file.read_text()
        chunks = chunk_code_file(content, Language.JS)

        assert len(chunks) >= 1
        assert all(isinstance(c, str) for c in chunks)

    def test_chunk_unknown_language(self, temp_dir: Path):
        """Test chunking unknown language falls back to generic."""
        file_path = temp_dir / "data.xyz"
        content = "line 1\nline 2\nline 3\n" * 100
        file_path.write_text(content)

        chunks = chunk_code_file(content, None)
        assert len(chunks) >= 1

    def test_chunk_respects_size(self, temp_dir: Path):
        """Test that chunks respect size limits."""
        # Create a large file
        content = "x" * 5000
        chunks = chunk_code_file(content, None, chunk_size=1000, chunk_overlap=100)

        assert len(chunks) > 1
        assert all(len(c) <= 1000 for c in chunks)


class TestScopeExtraction:
    """Tests for function/class scope extraction from code chunks."""

    def test_extract_python_function(self):
        """Test extracting Python function name."""
        chunk = '''def calculate_total(items):
    """Calculate total price."""
    return sum(item.price for item in items)
'''
        result = extract_scope_from_chunk(chunk, Language.PYTHON)
        assert result["function_name"] == "calculate_total"
        assert result["class_name"] is None
        assert result["scope"] == "calculate_total"

    def test_extract_python_class(self):
        """Test extracting Python class name."""
        chunk = '''class OrderService:
    """Service for managing orders."""

    def __init__(self, db):
        self.db = db
'''
        result = extract_scope_from_chunk(chunk, Language.PYTHON)
        assert result["class_name"] == "OrderService"
        assert result["function_name"] == "__init__"
        assert result["scope"] == "OrderService.__init__"

    def test_extract_python_async_function(self):
        """Test extracting async Python function."""
        chunk = '''async def fetch_data(url):
    async with aiohttp.ClientSession() as session:
        return await session.get(url)
'''
        result = extract_scope_from_chunk(chunk, Language.PYTHON)
        assert result["function_name"] == "fetch_data"
        assert result["scope"] == "fetch_data"

    def test_extract_javascript_function(self):
        """Test extracting JavaScript function name."""
        chunk = '''function validateInput(data) {
    if (!data.name) {
        throw new Error('Name required');
    }
}
'''
        result = extract_scope_from_chunk(chunk, Language.JS)
        assert result["function_name"] == "validateInput"
        assert result["scope"] == "validateInput"

    def test_extract_javascript_class(self):
        """Test extracting JavaScript class name."""
        chunk = '''class UserController {
    constructor(service) {
        this.service = service;
    }
}
'''
        result = extract_scope_from_chunk(chunk, Language.JS)
        assert result["class_name"] == "UserController"
        assert "class_name" in result

    def test_extract_go_function(self):
        """Test extracting Go function name."""
        chunk = '''func ProcessOrder(ctx context.Context, order *Order) error {
    if err := validate(order); err != nil {
        return err
    }
    return nil
}
'''
        result = extract_scope_from_chunk(chunk, Language.GO)
        assert result["function_name"] == "ProcessOrder"
        assert result["scope"] == "ProcessOrder"

    def test_extract_go_method(self):
        """Test extracting Go method with receiver."""
        chunk = '''func (s *Server) handleRequest(w http.ResponseWriter, r *http.Request) {
    // Handle the request
}
'''
        result = extract_scope_from_chunk(chunk, Language.GO)
        assert result["function_name"] == "handleRequest"

    def test_extract_rust_function(self):
        """Test extracting Rust function name."""
        chunk = '''pub async fn connect_database(config: &Config) -> Result<Pool, Error> {
    Pool::connect(&config.database_url).await
}
'''
        result = extract_scope_from_chunk(chunk, Language.RUST)
        assert result["function_name"] == "connect_database"

    def test_extract_no_scope_from_plain_text(self):
        """Test that plain text returns no scope."""
        chunk = "This is just a comment or documentation text."
        result = extract_scope_from_chunk(chunk, Language.PYTHON)
        assert result["function_name"] is None
        assert result["class_name"] is None
        assert result["scope"] is None

    def test_extract_none_language(self):
        """Test that None language returns empty result."""
        chunk = "def foo(): pass"
        result = extract_scope_from_chunk(chunk, None)
        assert result["function_name"] is None
        assert result["class_name"] is None
        assert result["scope"] is None

    def test_extract_innermost_function(self):
        """Test that the innermost function is extracted."""
        chunk = '''def outer():
    def inner():
        return "inner"
    return inner()
'''
        result = extract_scope_from_chunk(chunk, Language.PYTHON)
        # Should get the innermost (last) function
        assert result["function_name"] == "inner"


class TestIngestion:
    """Tests for file ingestion."""

    def test_ingest_single_file(self, sample_python_file: Path, temp_chroma_client):
        """Test ingesting a single file."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "test_ingest")

        doc_ids = ingest_file(
            file_path=sample_python_file,
            collection=collection,
            repo_id="test",
            branch="main",
            llm_provider="none",  # Skip LLM headers for testing
        )

        assert len(doc_ids) >= 1
        assert all(id.startswith("test:") for id in doc_ids)

        # Verify documents were added
        results = collection.get(ids=doc_ids)
        assert len(results["documents"]) == len(doc_ids)

    def test_ingest_file_metadata(self, sample_python_file: Path, temp_chroma_client):
        """Test that ingestion adds correct metadata."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "test_meta")

        ingest_file(
            file_path=sample_python_file,
            collection=collection,
            repo_id="myproject",
            branch="feature",
            llm_provider="none",
        )

        results = collection.get(include=["metadatas"])

        for meta in results["metadatas"]:
            assert meta["repository"] == "myproject"
            assert meta["branch"] == "feature"
            assert meta["language"] == "python"
            assert meta["type"] == "code"

    def test_ingest_scrubs_secrets(self, file_with_secrets: Path, temp_chroma_client):
        """Test that secrets are scrubbed during ingestion."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "test_scrub")

        ingest_file(
            file_path=file_with_secrets,
            collection=collection,
            repo_id="test",
            branch="main",
            llm_provider="none",
        )

        results = collection.get(include=["documents"])

        for doc in results["documents"]:
            # Secrets should be redacted
            assert "AKIAIOSFODNN7EXAMPLE" not in doc
            assert "ghp_" not in doc
            assert "sk_live_" not in doc

    def test_ingest_codebase(self, temp_dir: Path, temp_chroma_client):
        """Test full codebase ingestion."""
        from src.storage import get_or_create_collection

        # Create test files
        (temp_dir / "main.py").write_text("def main(): pass")
        (temp_dir / "utils.py").write_text("def helper(): pass")

        collection = get_or_create_collection(temp_chroma_client, "test_codebase")

        # Use a state file path that doesn't exist yet
        state_file = str(temp_dir / "ingest_state.json")

        stats = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            repo_id="myproject",
            llm_provider="none",
            state_file=state_file,
        )

        assert stats["files_scanned"] == 2
        assert stats["files_processed"] == 2
        assert stats["chunks_created"] >= 2
        assert stats["errors"] == []

    def test_ingest_codebase_delta(self, temp_dir: Path, temp_chroma_client):
        """Test delta sync in codebase ingestion."""
        from src.storage import get_or_create_collection

        # Create a subdirectory for code to avoid state file being picked up
        code_dir = temp_dir / "code"
        code_dir.mkdir()
        (code_dir / "main.py").write_text("def main(): pass")

        collection = get_or_create_collection(temp_chroma_client, "test_delta")

        # Use a state file outside the code directory
        state_file = str(temp_dir / "ingest_state.json")

        # First ingestion
        stats1 = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            llm_provider="none",
            state_file=state_file,
        )
        assert stats1["files_processed"] == 1

        # Second ingestion without changes
        stats2 = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            llm_provider="none",
            state_file=state_file,
        )
        # No files should be processed (unchanged)
        assert stats2["files_processed"] == 0

        # Modify file
        (code_dir / "main.py").write_text("def main(): print('changed')")

        # Third ingestion should process the changed file
        stats3 = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            llm_provider="none",
            state_file=state_file,
        )
        assert stats3["files_processed"] == 1

    def test_ingest_codebase_force_full(self, temp_dir: Path, temp_chroma_client):
        """Test force full re-ingestion."""
        from src.storage import get_or_create_collection

        # Create a subdirectory for code to avoid state file being picked up
        code_dir = temp_dir / "code"
        code_dir.mkdir()
        (code_dir / "main.py").write_text("def main(): pass")

        collection = get_or_create_collection(temp_chroma_client, "test_force")

        # Use a state file outside the code directory
        state_file = str(temp_dir / "ingest_state.json")

        # First ingestion
        ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            llm_provider="none",
            state_file=state_file,
        )

        # Force full re-ingestion
        stats = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            llm_provider="none",
            state_file=state_file,
            force_full=True,
        )

        # Should process all files even though unchanged
        assert stats["files_processed"] == 1

    def test_ingest_empty_file(self, temp_dir: Path, temp_chroma_client):
        """Test that empty files are skipped."""
        from src.storage import get_or_create_collection

        (temp_dir / "empty.py").write_text("")

        collection = get_or_create_collection(temp_chroma_client, "test_empty")

        doc_ids = ingest_file(
            file_path=temp_dir / "empty.py",
            collection=collection,
            repo_id="test",
            branch="main",
            llm_provider="none",
        )

        assert doc_ids == []


class TestSkeleton:
    """Tests for skeleton index functionality."""

    def test_generate_tree_fallback(self, temp_dir: Path):
        """Test Python fallback tree generation."""
        # Create test structure
        src_dir = temp_dir / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("print('hello')")
        (src_dir / "utils.py").write_text("def helper(): pass")

        tests_dir = temp_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_main.py").write_text("def test(): pass")

        (temp_dir / "README.md").write_text("# Project")

        from src.config import DEFAULT_IGNORE_PATTERNS

        tree = _generate_tree_fallback(temp_dir, max_depth=10, ignore=DEFAULT_IGNORE_PATTERNS)

        # Check structure
        assert temp_dir.name in tree
        assert "src" in tree
        assert "main.py" in tree
        assert "utils.py" in tree
        assert "tests" in tree
        assert "test_main.py" in tree
        assert "README.md" in tree
        assert "├──" in tree or "└──" in tree  # Tree formatting

    def test_generate_tree_fallback_respects_ignore(self, temp_dir: Path):
        """Test that tree fallback respects ignore patterns."""
        (temp_dir / "main.py").write_text("print('hello')")

        nm_dir = temp_dir / "node_modules"
        nm_dir.mkdir()
        (nm_dir / "package.js").write_text("module.exports = {}")

        from src.config import DEFAULT_IGNORE_PATTERNS

        tree = _generate_tree_fallback(temp_dir, max_depth=10, ignore=DEFAULT_IGNORE_PATTERNS)

        assert "main.py" in tree
        assert "node_modules" not in tree
        assert "package.js" not in tree

    def test_generate_tree_fallback_respects_depth(self, temp_dir: Path):
        """Test that tree fallback respects max depth."""
        # Create nested structure
        current = temp_dir
        for i in range(5):
            current = current / f"level{i}"
            current.mkdir()
            (current / f"file{i}.py").write_text(f"# level {i}")

        from src.config import DEFAULT_IGNORE_PATTERNS

        tree = _generate_tree_fallback(temp_dir, max_depth=2, ignore=DEFAULT_IGNORE_PATTERNS)

        # Should include levels 0-2 but not deeper
        assert "level0" in tree
        assert "level1" in tree
        assert "level2" in tree
        # level3 and beyond should not be included
        lines = tree.split("\n")
        assert not any("level3" in line for line in lines)

    def test_analyze_tree(self):
        """Test tree stats extraction."""
        tree = """myproject
├── src
│   ├── main.py
│   └── utils.py
├── tests
│   └── test_main.py
└── README.md"""

        stats = _analyze_tree(tree)

        assert stats["total_lines"] == 7
        assert stats["total_files"] >= 3  # main.py, utils.py, test_main.py, README.md
        assert stats["total_dirs"] >= 2  # src, tests

    def test_generate_tree_structure(self, temp_dir: Path):
        """Test full tree generation (with fallback)."""
        (temp_dir / "main.py").write_text("print('hello')")
        (temp_dir / "README.md").write_text("# Project")

        tree, stats = generate_tree_structure(str(temp_dir))

        assert temp_dir.name in tree
        assert "main.py" in tree
        assert "README.md" in tree
        assert "total_files" in stats
        assert "total_dirs" in stats
        assert stats["total_lines"] >= 3

    def test_store_skeleton(self, temp_chroma_client):
        """Test skeleton storage in ChromaDB."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "test_skeleton")

        tree = """myproject
├── src
│   └── main.py
└── README.md"""
        stats = {"total_files": 2, "total_dirs": 1, "total_lines": 4}

        doc_id = store_skeleton(
            collection=collection,
            tree_output=tree,
            repo_id="myproject",
            branch="main",
            stats=stats,
        )

        assert doc_id == "myproject:skeleton:main"

        # Verify storage
        result = collection.get(ids=[doc_id], include=["documents", "metadatas"])
        assert len(result["documents"]) == 1
        assert result["documents"][0] == tree
        assert result["metadatas"][0]["type"] == "skeleton"
        assert result["metadatas"][0]["repository"] == "myproject"
        assert result["metadatas"][0]["branch"] == "main"
        assert result["metadatas"][0]["total_files"] == 2

    def test_ingest_codebase_creates_skeleton(self, temp_dir: Path, temp_chroma_client):
        """Test that ingest_codebase auto-generates skeleton."""
        from src.storage import get_or_create_collection

        # Create test files
        (temp_dir / "main.py").write_text("def main(): pass")
        (temp_dir / "utils.py").write_text("def helper(): pass")

        collection = get_or_create_collection(temp_chroma_client, "test_skel_ingest")

        # Use a state file path that doesn't exist yet
        state_file = str(temp_dir / "ingest_state.json")

        stats = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            repo_id="myproject",
            state_file=state_file,
        )

        # Check skeleton was created
        assert "skeleton" in stats
        assert stats["skeleton"]["total_files"] >= 2

        # Verify skeleton is stored
        skeleton_result = collection.get(
            where={"$and": [{"type": "skeleton"}, {"repository": "myproject"}]},
            include=["documents", "metadatas"],
        )
        assert len(skeleton_result["documents"]) == 1
        assert "main.py" in skeleton_result["documents"][0]
        assert "utils.py" in skeleton_result["documents"][0]


class TestGitIntegration:
    """Tests for git-based delta sync."""

    def test_is_git_repo_true(self, temp_dir: Path):
        """Test git repo detection in actual git repo."""
        import subprocess

        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)

        assert is_git_repo(str(temp_dir)) is True

    def test_is_git_repo_false(self, temp_dir: Path):
        """Test git repo detection in non-git directory."""
        assert is_git_repo(str(temp_dir)) is False

    def test_get_head_commit(self, temp_dir: Path):
        """Test getting HEAD commit hash."""
        import subprocess

        # Initialize git repo with a commit
        subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=temp_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=temp_dir,
            capture_output=True,
        )
        (temp_dir / "test.txt").write_text("content")
        subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_dir,
            capture_output=True,
        )

        commit = get_head_commit(str(temp_dir))

        assert commit is not None
        assert len(commit) == 40  # SHA-1 hash length

    def test_get_head_commit_no_commits(self, temp_dir: Path):
        """Test HEAD commit in repo with no commits."""
        import subprocess

        subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)

        commit = get_head_commit(str(temp_dir))

        assert commit is None

    def test_get_git_changed_files(self, temp_dir: Path):
        """Test git-based change detection."""
        import subprocess

        # Initialize git repo with initial commit
        subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=temp_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=temp_dir,
            capture_output=True,
        )
        (temp_dir / "file1.py").write_text("original")
        subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_dir,
            capture_output=True,
        )

        initial_commit = get_head_commit(str(temp_dir))

        # Make changes: modify file1, add file2, delete file3
        (temp_dir / "file1.py").write_text("modified")
        (temp_dir / "file2.py").write_text("new file")
        subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "changes"],
            cwd=temp_dir,
            capture_output=True,
        )

        modified, deleted, renamed = get_git_changed_files(str(temp_dir), initial_commit)

        assert any("file1.py" in f for f in modified)
        assert any("file2.py" in f for f in modified)
        assert deleted == []
        assert renamed == []

    def test_get_git_changed_files_with_delete(self, temp_dir: Path):
        """Test git detects deleted files."""
        import subprocess

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=temp_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=temp_dir,
            capture_output=True,
        )
        (temp_dir / "to_delete.py").write_text("will be deleted")
        (temp_dir / "keep.py").write_text("keep this")
        subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_dir,
            capture_output=True,
        )

        initial_commit = get_head_commit(str(temp_dir))

        # Delete file
        (temp_dir / "to_delete.py").unlink()
        subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "delete file"],
            cwd=temp_dir,
            capture_output=True,
        )

        modified, deleted, renamed = get_git_changed_files(str(temp_dir), initial_commit)

        assert any("to_delete.py" in f for f in deleted)
        assert not any("keep.py" in f for f in deleted)

    def test_get_git_changed_files_with_rename(self, temp_dir: Path):
        """Test git detects renamed files."""
        import subprocess

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=temp_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=temp_dir,
            capture_output=True,
        )
        (temp_dir / "old_name.py").write_text("content")
        subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_dir,
            capture_output=True,
        )

        initial_commit = get_head_commit(str(temp_dir))

        # Rename file
        (temp_dir / "old_name.py").rename(temp_dir / "new_name.py")
        subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "rename file"],
            cwd=temp_dir,
            capture_output=True,
        )

        modified, deleted, renamed = get_git_changed_files(str(temp_dir), initial_commit)

        # Renamed files should appear in renamed list
        assert len(renamed) == 1
        old_path, new_path = renamed[0]
        assert "old_name.py" in old_path
        assert "new_name.py" in new_path
        # New path should also be in modified for indexing
        assert any("new_name.py" in f for f in modified)

    def test_get_untracked_files(self, temp_dir: Path):
        """Test detection of untracked files."""
        import os
        import subprocess

        subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=temp_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=temp_dir,
            capture_output=True,
        )

        # Create initial tracked file
        (temp_dir / "committed_file.py").write_text("tracked")
        subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_dir,
            capture_output=True,
        )

        # Add untracked file
        (temp_dir / "new_untracked.py").write_text("untracked")

        untracked = get_untracked_files(str(temp_dir))

        # Check by filename to avoid path substring issues
        untracked_names = [os.path.basename(f) for f in untracked]
        assert "new_untracked.py" in untracked_names
        assert "committed_file.py" not in untracked_names


class TestGarbageCollection:
    """Tests for garbage collection functionality."""

    def test_delete_file_chunks(self, temp_dir: Path, temp_chroma_client):
        """Test deleting chunks for a file."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "test_gc")

        # Add some chunks
        collection.upsert(
            ids=["proj:file1.py:0", "proj:file1.py:1", "proj:file2.py:0"],
            documents=["chunk 1", "chunk 2", "chunk 3"],
            metadatas=[
                {"file_path": "/path/to/file1.py", "repository": "proj", "type": "code"},
                {"file_path": "/path/to/file1.py", "repository": "proj", "type": "code"},
                {"file_path": "/path/to/file2.py", "repository": "proj", "type": "code"},
            ],
        )

        # Delete chunks for file1
        deleted = delete_file_chunks(collection, ["/path/to/file1.py"], "proj")

        assert deleted == 2

        # Verify file1 chunks are gone, file2 chunks remain
        results = collection.get(include=["metadatas"])
        assert len(results["ids"]) == 1
        assert results["metadatas"][0]["file_path"] == "/path/to/file2.py"

    def test_delete_file_chunks_empty_list(self, temp_chroma_client):
        """Test that empty file list does nothing."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "test_gc_empty")

        deleted = delete_file_chunks(collection, [], "proj")

        assert deleted == 0

    def test_cleanup_state_entries(self):
        """Test cleaning up state entries for deleted files."""
        state = {
            "file_hashes": {
                "/path/to/file1.py": "hash1",
                "/path/to/file2.py": "hash2",
                "/path/to/file3.py": "hash3",
            },
            "indexed_commit": "abc123",
        }

        cleanup_state_entries(state, ["/path/to/file1.py", "/path/to/file3.py"])

        assert "/path/to/file1.py" not in state["file_hashes"]
        assert "/path/to/file2.py" in state["file_hashes"]
        assert "/path/to/file3.py" not in state["file_hashes"]


class TestStateFormat:
    """Tests for state format migration and handling."""

    def test_state_migration_old_to_new(self, temp_dir: Path, temp_chroma_client):
        """Test that old state format is migrated to new format."""
        from src.storage import get_or_create_collection

        # Create old-format state file
        state_file = temp_dir / "state.json"
        old_state = {
            "/path/to/file1.py": "hash1",
            "/path/to/file2.py": "hash2",
        }
        state_file.write_text(json.dumps(old_state))

        # Create a code directory
        code_dir = temp_dir / "code"
        code_dir.mkdir()
        (code_dir / "main.py").write_text("def main(): pass")

        collection = get_or_create_collection(temp_chroma_client, "test_migrate")

        # Run ingestion
        ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            llm_provider="none",
            state_file=str(state_file),
        )

        # Load updated state
        new_state = load_state(str(state_file))

        # Verify new format
        assert "file_hashes" in new_state
        assert "indexed_at" in new_state
        assert "repository" in new_state

    def test_atomic_state_write(self, temp_dir: Path):
        """Test that state writes are atomic."""
        state_file = temp_dir / "state.json"
        state = {
            "file_hashes": {"file.py": "hash"},
            "indexed_commit": "abc123",
            "indexed_at": "2024-01-01T00:00:00Z",
        }

        save_state(state, str(state_file))

        # Verify file exists and is valid JSON
        loaded = load_state(str(state_file))
        assert loaded == state

    def test_ingest_reports_delta_mode(self, temp_dir: Path, temp_chroma_client):
        """Test that ingestion reports which delta mode was used."""
        from src.storage import get_or_create_collection

        code_dir = temp_dir / "code"
        code_dir.mkdir()
        (code_dir / "main.py").write_text("def main(): pass")

        collection = get_or_create_collection(temp_chroma_client, "test_mode")
        state_file = str(temp_dir / "state.json")

        # First run should use hash mode (first index of non-git dir)
        stats = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            llm_provider="none",
            state_file=state_file,
        )

        assert "delta_mode" in stats
        # Non-git dir on first run uses hash-based
        assert stats["delta_mode"] in ("hash", "full")

    def test_ingest_tracks_deleted_stats(self, temp_dir: Path, temp_chroma_client):
        """Test that ingestion tracks deletion stats."""
        from src.storage import get_or_create_collection

        code_dir = temp_dir / "code"
        code_dir.mkdir()
        (code_dir / "main.py").write_text("def main(): pass")

        collection = get_or_create_collection(temp_chroma_client, "test_del_stats")
        state_file = str(temp_dir / "state.json")

        stats = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            llm_provider="none",
            state_file=state_file,
        )

        assert "files_deleted" in stats
        assert "chunks_deleted" in stats
        assert stats["files_deleted"] == 0  # No deletions on first run


class TestSelectiveIngestion:
    """Tests for selective ingestion with include_patterns and cortexignore."""

    def test_include_patterns_single(self, temp_dir: Path):
        """Test that include_patterns filters to only matching files."""
        # Create directory structure
        src_dir = temp_dir / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("def main(): pass")

        tests_dir = temp_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_main.py").write_text("def test(): pass")

        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "readme.md").write_text("# Readme")

        # Only include src/**
        files = list(walk_codebase(str(temp_dir), include_patterns=["src/**"]))
        file_names = [f.name for f in files]

        assert "main.py" in file_names
        assert "test_main.py" not in file_names
        assert "readme.md" not in file_names

    def test_include_patterns_multiple(self, temp_dir: Path):
        """Test that multiple include_patterns are ORed together."""
        # Create directory structure
        src_dir = temp_dir / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("def main(): pass")

        tests_dir = temp_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_main.py").write_text("def test(): pass")

        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "readme.md").write_text("# Readme")

        # Include src/** OR tests/**
        files = list(walk_codebase(str(temp_dir), include_patterns=["src/**", "tests/**"]))
        file_names = [f.name for f in files]

        assert "main.py" in file_names
        assert "test_main.py" in file_names
        assert "readme.md" not in file_names

    def test_include_patterns_nested(self, temp_dir: Path):
        """Test include patterns with deeply nested paths."""
        # Create nested structure
        api_dir = temp_dir / "packages" / "api" / "src"
        api_dir.mkdir(parents=True)
        (api_dir / "handler.py").write_text("def handle(): pass")

        web_dir = temp_dir / "packages" / "web" / "src"
        web_dir.mkdir(parents=True)
        (web_dir / "app.js").write_text("const app = {}")

        files = list(walk_codebase(str(temp_dir), include_patterns=["packages/api/**"]))
        file_names = [f.name for f in files]

        assert "handler.py" in file_names
        assert "app.js" not in file_names

    def test_project_cortexignore(self, temp_dir: Path):
        """Test that project .cortexignore is respected."""
        # Create files
        (temp_dir / "main.py").write_text("def main(): pass")

        fixtures_dir = temp_dir / "fixtures"
        fixtures_dir.mkdir()
        (fixtures_dir / "data.json").write_text("{}")

        # Create project .cortexignore
        (temp_dir / ".cortexignore").write_text("fixtures\n")

        files = list(walk_codebase(str(temp_dir), use_cortexignore=True))
        file_names = [f.name for f in files]

        assert "main.py" in file_names
        assert "data.json" not in file_names

    def test_project_cortexignore_comments(self, temp_dir: Path):
        """Test that .cortexignore handles comments correctly."""
        (temp_dir / "main.py").write_text("def main(): pass")
        (temp_dir / "generated.py").write_text("# auto-generated")

        # Create .cortexignore with comments
        (temp_dir / ".cortexignore").write_text("""
# This is a comment
generated.py
# Another comment
""")

        files = list(walk_codebase(str(temp_dir), use_cortexignore=True))
        file_names = [f.name for f in files]

        assert "main.py" in file_names
        assert "generated.py" not in file_names

    def test_disable_cortexignore(self, temp_dir: Path):
        """Test that use_cortexignore=False skips cortexignore files."""
        (temp_dir / "main.py").write_text("def main(): pass")
        (temp_dir / "ignored.py").write_text("# should not be ignored")

        # Create .cortexignore that would ignore ignored.py
        (temp_dir / ".cortexignore").write_text("ignored.py\n")

        # With cortexignore disabled, ignored.py should be included
        files = list(walk_codebase(str(temp_dir), use_cortexignore=False))
        file_names = [f.name for f in files]

        assert "main.py" in file_names
        assert "ignored.py" in file_names

    def test_include_patterns_with_cortexignore(self, temp_dir: Path):
        """Test that include_patterns and cortexignore work together."""
        # Create structure
        src_dir = temp_dir / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("def main(): pass")
        (src_dir / "generated.py").write_text("# generated")

        tests_dir = temp_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_main.py").write_text("def test(): pass")

        # cortexignore excludes generated files
        (temp_dir / ".cortexignore").write_text("**/generated.py\n")

        # Include only src/**
        files = list(walk_codebase(
            str(temp_dir),
            include_patterns=["src/**"],
            use_cortexignore=True,
        ))
        file_names = [f.name for f in files]

        # main.py should be included (in src/, not ignored)
        assert "main.py" in file_names
        # generated.py should be excluded (by cortexignore)
        assert "generated.py" not in file_names
        # test_main.py should be excluded (not in include pattern)
        assert "test_main.py" not in file_names

    def test_ingest_codebase_with_include_patterns(self, temp_dir: Path, temp_chroma_client):
        """Test ingest_codebase with include_patterns."""
        from src.storage import get_or_create_collection

        # Create structure
        src_dir = temp_dir / "code" / "src"
        src_dir.mkdir(parents=True)
        (src_dir / "main.py").write_text("def main(): pass")

        docs_dir = temp_dir / "code" / "docs"
        docs_dir.mkdir()
        (docs_dir / "readme.md").write_text("# Readme")

        collection = get_or_create_collection(temp_chroma_client, "test_include")
        code_dir = temp_dir / "code"
        state_file = str(temp_dir / "state.json")

        stats = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            repo_id="test",
            llm_provider="none",
            state_file=state_file,
            include_patterns=["src/**"],
        )

        # Should only process src/main.py, not docs/readme.md
        assert stats["files_processed"] == 1
        assert stats["files_scanned"] == 1

    def test_skeleton_respects_include_patterns(self, temp_dir: Path):
        """Test that skeleton generation respects include_patterns."""
        # Create structure
        src_dir = temp_dir / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("def main(): pass")

        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "readme.md").write_text("# Readme")

        tree, stats = generate_tree_structure(
            str(temp_dir),
            include_patterns=["src/**"],
        )

        assert "src" in tree
        assert "main.py" in tree
        # docs should not appear since it doesn't match pattern
        assert "docs" not in tree
        assert "readme.md" not in tree
