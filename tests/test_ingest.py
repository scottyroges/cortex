"""
Tests for ingest module
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.configs.ignore_patterns import DEFAULT_IGNORE_PATTERNS
from src.external.git import get_git_changed_files, get_head_commit, get_untracked_files, is_git_repo
from src.tools.ingest import (
    compute_file_hash,
    generate_tree_structure,
    get_changed_files,
    ingest_codebase,
    store_skeleton,
    walk_codebase,
)
from src.tools.ingest.skeleton import _analyze_tree, _generate_tree_fallback
from src.storage import delete_file_chunks, get_or_create_collection


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

class TestIngestion:
    """Tests for metadata-first file ingestion."""

    def test_ingest_codebase(self, temp_dir: Path, temp_chroma_client):
        """Test full codebase ingestion with metadata-first approach."""
        from src.storage import get_or_create_collection

        # Create test files
        (temp_dir / "main.py").write_text("def main(): pass")
        (temp_dir / "utils.py").write_text("def helper(): pass")

        collection = get_or_create_collection(temp_chroma_client, "test_codebase")

        # Use a state file path that doesn't exist yet

        stats = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            repo_id="myproject",
            
        )

        assert stats["files_scanned"] == 2
        assert stats["files_processed"] == 2
        # metadata-first creates docs
        assert stats["docs_created"] >= 2
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

        # First ingestion
        stats1 = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            
        )
        assert stats1["files_processed"] == 1

        # Second ingestion without changes
        stats2 = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            
        )
        # No files should be processed (unchanged)
        assert stats2["files_processed"] == 0

        # Modify file
        (code_dir / "main.py").write_text("def main(): print('changed')")

        # Third ingestion should process the changed file
        stats3 = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            
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

        # First ingestion
        ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            
        )

        # Force full re-ingestion
        stats = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            
            force_full=True,
        )

        # Should process all files even though unchanged
        assert stats["files_processed"] == 1

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

        from src.configs.ignore_patterns import DEFAULT_IGNORE_PATTERNS

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

        from src.configs.ignore_patterns import DEFAULT_IGNORE_PATTERNS

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

        from src.configs.ignore_patterns import DEFAULT_IGNORE_PATTERNS

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

        stats = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            repo_id="myproject",
            
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

        stats = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            repo_id="test",
            
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


class TestMetadataFirstIngestion:
    """Tests for metadata-first ingestion approach."""

    def test_ingest_metadata_creates_file_metadata(self, temp_dir: Path, temp_chroma_client):
        """Test that metadata-first ingestion creates file_metadata documents."""
        from src.storage import get_or_create_collection

        # Create a Python file with a class
        (temp_dir / "service.py").write_text('''
"""User service module."""
from typing import Optional

class UserService:
    """Service for user operations."""

    def get_user(self, user_id: int) -> Optional[dict]:
        """Get user by ID."""
        pass

    def create_user(self, name: str) -> dict:
        """Create a new user."""
        pass
''')

        collection = get_or_create_collection(temp_chroma_client, "test_metadata")

        stats = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            repo_id="test",
            
        )

        assert stats["files_processed"] >= 1
        assert stats["docs_created"] >= 1

        # Verify file_metadata document was created
        results = collection.get(
            where={"type": "file_metadata"},
            include=["documents", "metadatas"],
        )

        assert len(results["ids"]) >= 1
        meta = results["metadatas"][0]
        assert meta["repository"] == "test"
        assert meta["language"] == "python"
        assert "UserService" in meta.get("exports", "")

    def test_ingest_metadata_creates_data_contracts(self, temp_dir: Path, temp_chroma_client):
        """Test that metadata-first ingestion creates data_contract documents for dataclasses."""
        from src.storage import get_or_create_collection

        # Create a Python file with a dataclass
        (temp_dir / "models.py").write_text('''
from dataclasses import dataclass
from typing import Optional

@dataclass
class User:
    """User data model."""
    id: int
    name: str
    email: Optional[str] = None
''')

        collection = get_or_create_collection(temp_chroma_client, "test_contracts")

        stats = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            repo_id="test",
            
        )

        # Verify data_contract document was created
        results = collection.get(
            where={"type": "data_contract"},
            include=["documents", "metadatas"],
        )

        assert len(results["ids"]) >= 1
        meta = results["metadatas"][0]
        assert meta["name"] == "User"
        assert meta["contract_type"] == "dataclass"
        assert "id" in meta.get("fields", "")
        assert "name" in meta.get("fields", "")

    def test_ingest_metadata_creates_entry_points(self, temp_dir: Path, temp_chroma_client):
        """Test that metadata-first ingestion creates entry_point documents."""
        from src.storage import get_or_create_collection

        # Create a main entry point file
        (temp_dir / "main.py").write_text('''
"""Main application entry point."""

def main():
    """Start the application."""
    print("Starting...")

if __name__ == "__main__":
    main()
''')

        collection = get_or_create_collection(temp_chroma_client, "test_entry")

        stats = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            repo_id="test",
            
        )

        # Verify entry_point document was created
        results = collection.get(
            where={"type": "entry_point"},
            include=["documents", "metadatas"],
        )

        assert len(results["ids"]) >= 1
        meta = results["metadatas"][0]
        assert meta["entry_type"] == "main"
        assert "main.py" in meta["file_path"]

    def test_ingest_metadata_creates_dependencies(self, temp_dir: Path, temp_chroma_client):
        """Test that metadata-first ingestion creates dependency documents."""
        from src.storage import get_or_create_collection

        # Create files with internal imports using relative imports
        src_dir = temp_dir / "src"
        src_dir.mkdir()

        (src_dir / "__init__.py").write_text("")

        (src_dir / "models.py").write_text('''
class User:
    pass
''')

        (src_dir / "service.py").write_text('''
from .models import User

class UserService:
    def get_user(self) -> User:
        pass
''')

        collection = get_or_create_collection(temp_chroma_client, "test_deps")

        stats = ingest_codebase(
            root_path=str(src_dir),
            collection=collection,
            repo_id="test",
            
        )

        # Verify dependency documents were created
        results = collection.get(
            where={"type": "dependency"},
            include=["documents", "metadatas"],
        )

        # At least one dependency document should exist for the import relationship
        assert len(results["ids"]) >= 1

    def test_ingest_metadata_no_code_chunks(self, temp_dir: Path, temp_chroma_client):
        """Test that metadata-first ingestion does NOT create code chunks."""
        from src.storage import get_or_create_collection

        (temp_dir / "main.py").write_text('''
def hello():
    print("Hello world")
''')

        collection = get_or_create_collection(temp_chroma_client, "test_no_chunks")

        ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            repo_id="test",
            
        )

        # Verify NO code chunks were created
        results = collection.get(
            where={"type": "code"},
            include=["metadatas"],
        )

        assert len(results["ids"]) == 0

    def test_ingest_metadata_unsupported_language_skipped(self, temp_dir: Path, temp_chroma_client):
        """Test that unsupported languages are gracefully skipped in metadata mode."""
        from src.storage import get_or_create_collection

        # Create files in supported and unsupported languages
        (temp_dir / "main.py").write_text("def main(): pass")
        (temp_dir / "style.css").write_text("body { color: red; }")

        collection = get_or_create_collection(temp_chroma_client, "test_unsupported")

        stats = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            repo_id="test",
            
        )

        # Python file should be processed, CSS skipped
        assert stats["files_processed"] == 1
        assert stats["files_skipped"] >= 1

    def test_ingest_metadata_typescript(self, temp_dir: Path, temp_chroma_client):
        """Test metadata-first ingestion of TypeScript files."""
        from src.storage import get_or_create_collection

        (temp_dir / "types.ts").write_text('''
export interface User {
    id: number;
    name: string;
    email?: string;
}

export type UserRole = "admin" | "user" | "guest";
''')

        collection = get_or_create_collection(temp_chroma_client, "test_ts")

        stats = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            repo_id="test",
            
        )

        assert stats["files_processed"] == 1

        # Verify data_contract documents for interfaces
        results = collection.get(
            where={"type": "data_contract"},
            include=["metadatas"],
        )

        contract_names = [m["name"] for m in results["metadatas"]]
        assert "User" in contract_names

    def test_ingest_metadata_delta_sync(self, temp_dir: Path, temp_chroma_client):
        """Test that delta sync works with metadata-first ingestion."""
        from src.storage import get_or_create_collection

        code_dir = temp_dir / "code"
        code_dir.mkdir()
        (code_dir / "main.py").write_text("def main(): pass")

        collection = get_or_create_collection(temp_chroma_client, "test_meta_delta")

        # First ingestion
        stats1 = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            repo_id="test",
            
        )
        assert stats1["files_processed"] == 1

        # Second ingestion without changes
        stats2 = ingest_codebase(
            root_path=str(code_dir),
            collection=collection,
            repo_id="test",
            
        )
        # Should skip unchanged files
        assert stats2["files_processed"] == 0
