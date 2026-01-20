"""
Tests for garbage collection functions (cleanup and purge).
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.storage import get_or_create_collection
from src.storage.gc import (
    cleanup_orphaned_file_metadata,
    cleanup_orphaned_insights,
    cleanup_orphaned_dependencies,
    purge_by_filters,
)


class TestCleanupOrphanedFileMetadata:
    """Tests for cleanup_orphaned_file_metadata function."""

    def test_no_orphans_when_files_exist(self, temp_chroma_client, temp_dir):
        """Test that existing files are not marked as orphaned."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        # Create actual file
        test_file = temp_dir / "existing.py"
        test_file.write_text("print('hello')")

        # Add file_metadata for existing file
        collection.add(
            documents=["File metadata for existing.py"],
            ids=["file_metadata:existing.py"],
            metadatas=[{
                "type": "file_metadata",
                "repository": "test-repo",
                "file_path": "existing.py",
            }],
        )

        result = cleanup_orphaned_file_metadata(
            collection, str(temp_dir), "test-repo", dry_run=True
        )

        assert result["count"] == 0
        assert result["deleted"] == 0
        assert result["orphaned_files"] == []

    def test_detects_orphaned_files(self, temp_chroma_client, temp_dir):
        """Test that missing files are detected as orphaned."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        # Add file_metadata for non-existent file
        collection.add(
            documents=["File metadata for deleted.py"],
            ids=["file_metadata:deleted.py"],
            metadatas=[{
                "type": "file_metadata",
                "repository": "test-repo",
                "file_path": "deleted.py",
            }],
        )

        result = cleanup_orphaned_file_metadata(
            collection, str(temp_dir), "test-repo", dry_run=True
        )

        assert result["count"] == 1
        assert result["deleted"] == 0  # dry_run=True
        assert "deleted.py" in result["orphaned_files"]

    def test_deletes_orphans_when_not_dry_run(self, temp_chroma_client, temp_dir):
        """Test that orphaned records are deleted when dry_run=False."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        # Add file_metadata for non-existent file
        collection.add(
            documents=["File metadata for deleted.py"],
            ids=["file_metadata:deleted.py"],
            metadatas=[{
                "type": "file_metadata",
                "repository": "test-repo",
                "file_path": "deleted.py",
            }],
        )

        result = cleanup_orphaned_file_metadata(
            collection, str(temp_dir), "test-repo", dry_run=False
        )

        assert result["count"] == 1
        assert result["deleted"] == 1

        # Verify deletion
        remaining = collection.get(ids=["file_metadata:deleted.py"])
        assert len(remaining["ids"]) == 0

    def test_filters_by_repository(self, temp_chroma_client, temp_dir):
        """Test that cleanup only affects specified repository."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        # Add file_metadata for different repos
        collection.add(
            documents=["Repo A metadata", "Repo B metadata"],
            ids=["file_metadata:a.py", "file_metadata:b.py"],
            metadatas=[
                {"type": "file_metadata", "repository": "repo-a", "file_path": "a.py"},
                {"type": "file_metadata", "repository": "repo-b", "file_path": "b.py"},
            ],
        )

        result = cleanup_orphaned_file_metadata(
            collection, str(temp_dir), "repo-a", dry_run=False
        )

        assert result["count"] == 1
        assert result["deleted"] == 1

        # repo-b's file should still exist
        remaining = collection.get(ids=["file_metadata:b.py"])
        assert len(remaining["ids"]) == 1


class TestCleanupOrphanedInsights:
    """Tests for cleanup_orphaned_insights function."""

    def test_no_orphans_when_files_exist(self, temp_chroma_client, temp_dir):
        """Test that insights with existing files are not orphaned."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        # Create actual file
        test_file = temp_dir / "existing.py"
        test_file.write_text("print('hello')")

        # Add insight linked to existing file
        collection.add(
            documents=["Insight about existing.py"],
            ids=["insight:001"],
            metadatas=[{
                "type": "insight",
                "repository": "test-repo",
                "files": json.dumps(["existing.py"]),
            }],
        )

        result = cleanup_orphaned_insights(
            collection, str(temp_dir), "test-repo", dry_run=True
        )

        assert result["count"] == 0

    def test_detects_orphaned_insights(self, temp_chroma_client, temp_dir):
        """Test that insights linked to missing files are detected."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        # Add insight linked to non-existent file
        collection.add(
            documents=["Insight about deleted.py"],
            ids=["insight:002"],
            metadatas=[{
                "type": "insight",
                "repository": "test-repo",
                "files": json.dumps(["deleted.py"]),
            }],
        )

        result = cleanup_orphaned_insights(
            collection, str(temp_dir), "test-repo", dry_run=True
        )

        assert result["count"] == 1
        assert "insight:002" in result["orphaned_ids"]

    def test_keeps_insight_if_any_file_exists(self, temp_chroma_client, temp_dir):
        """Test that insight is kept if at least one linked file exists."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        # Create one of the files
        test_file = temp_dir / "existing.py"
        test_file.write_text("print('hello')")

        # Add insight linked to multiple files (one exists, one doesn't)
        collection.add(
            documents=["Insight about multiple files"],
            ids=["insight:003"],
            metadatas=[{
                "type": "insight",
                "repository": "test-repo",
                "files": json.dumps(["existing.py", "deleted.py"]),
            }],
        )

        result = cleanup_orphaned_insights(
            collection, str(temp_dir), "test-repo", dry_run=True
        )

        # Should not be orphaned since existing.py exists
        assert result["count"] == 0

    def test_deletes_orphaned_insights(self, temp_chroma_client, temp_dir):
        """Test that orphaned insights are deleted when dry_run=False."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        collection.add(
            documents=["Orphaned insight"],
            ids=["insight:orphan"],
            metadatas=[{
                "type": "insight",
                "repository": "test-repo",
                "files": json.dumps(["nonexistent.py"]),
            }],
        )

        result = cleanup_orphaned_insights(
            collection, str(temp_dir), "test-repo", dry_run=False
        )

        assert result["deleted"] == 1

        remaining = collection.get(ids=["insight:orphan"])
        assert len(remaining["ids"]) == 0

    def test_skips_insights_without_files(self, temp_chroma_client, temp_dir):
        """Test that insights without file links are not considered orphaned."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        # Insight with no files (general note-style insight)
        collection.add(
            documents=["General insight without file links"],
            ids=["insight:general"],
            metadatas=[{
                "type": "insight",
                "repository": "test-repo",
                "files": "[]",
            }],
        )

        result = cleanup_orphaned_insights(
            collection, str(temp_dir), "test-repo", dry_run=True
        )

        assert result["count"] == 0


class TestCleanupOrphanedDependencies:
    """Tests for cleanup_orphaned_dependencies function."""

    def test_no_orphans_when_files_exist(self, temp_chroma_client, temp_dir):
        """Test that dependencies for existing files are not orphaned."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        # Create actual file
        test_file = temp_dir / "module.py"
        test_file.write_text("import os")

        collection.add(
            documents=["module.py -> os"],
            ids=["dep:module.py"],
            metadatas=[{
                "type": "dependency",
                "repository": "test-repo",
                "file_path": "module.py",
            }],
        )

        result = cleanup_orphaned_dependencies(
            collection, str(temp_dir), "test-repo", dry_run=True
        )

        assert result["count"] == 0

    def test_detects_orphaned_dependencies(self, temp_chroma_client, temp_dir):
        """Test that dependencies for missing files are detected."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        collection.add(
            documents=["deleted.py -> os"],
            ids=["dep:deleted.py"],
            metadatas=[{
                "type": "dependency",
                "repository": "test-repo",
                "file_path": "deleted.py",
            }],
        )

        result = cleanup_orphaned_dependencies(
            collection, str(temp_dir), "test-repo", dry_run=True
        )

        assert result["count"] == 1

    def test_deletes_orphaned_dependencies(self, temp_chroma_client, temp_dir):
        """Test that orphaned dependencies are deleted when dry_run=False."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        collection.add(
            documents=["orphan.py -> something"],
            ids=["dep:orphan"],
            metadatas=[{
                "type": "dependency",
                "repository": "test-repo",
                "file_path": "orphan.py",
            }],
        )

        result = cleanup_orphaned_dependencies(
            collection, str(temp_dir), "test-repo", dry_run=False
        )

        assert result["deleted"] == 1

        remaining = collection.get(ids=["dep:orphan"])
        assert len(remaining["ids"]) == 0


class TestPurgeByFilters:
    """Tests for purge_by_filters function."""

    def test_purge_by_repository(self, temp_chroma_client):
        """Test purging documents by repository."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        collection.add(
            documents=["Doc from repo-a", "Doc from repo-b"],
            ids=["doc1", "doc2"],
            metadatas=[
                {"type": "note", "repository": "repo-a"},
                {"type": "note", "repository": "repo-b"},
            ],
        )

        result = purge_by_filters(collection, repository="repo-a", dry_run=True)

        assert result["matched_count"] == 1
        assert result["deleted_count"] == 0  # dry_run
        assert "doc1" in result["sample_ids"]

    def test_purge_by_type(self, temp_chroma_client):
        """Test purging documents by type."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        collection.add(
            documents=["A note", "An insight", "Another note"],
            ids=["note1", "insight1", "note2"],
            metadatas=[
                {"type": "note", "repository": "test"},
                {"type": "insight", "repository": "test"},
                {"type": "note", "repository": "test"},
            ],
        )

        result = purge_by_filters(collection, doc_type="note", dry_run=True)

        assert result["matched_count"] == 2
        assert "note1" in result["sample_ids"]
        assert "note2" in result["sample_ids"]
        assert "insight1" not in result["sample_ids"]

    def test_purge_by_branch(self, temp_chroma_client):
        """Test purging documents by branch."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        collection.add(
            documents=["Main branch doc", "Feature branch doc"],
            ids=["main-doc", "feature-doc"],
            metadatas=[
                {"type": "note", "repository": "test", "branch": "main"},
                {"type": "note", "repository": "test", "branch": "feature/test"},
            ],
        )

        result = purge_by_filters(collection, branch="feature/test", dry_run=True)

        assert result["matched_count"] == 1
        assert "feature-doc" in result["sample_ids"]

    def test_purge_by_date_before(self, temp_chroma_client):
        """Test purging documents created before a date."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        old_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        new_date = datetime.now(timezone.utc).isoformat()

        collection.add(
            documents=["Old doc", "New doc"],
            ids=["old", "new"],
            metadatas=[
                {"type": "note", "repository": "test", "created_at": old_date},
                {"type": "note", "repository": "test", "created_at": new_date},
            ],
        )

        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        result = purge_by_filters(
            collection, repository="test", before_date=cutoff, dry_run=True
        )

        assert result["matched_count"] == 1
        assert "old" in result["sample_ids"]

    def test_purge_by_date_after(self, temp_chroma_client):
        """Test purging documents created after a date."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        old_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        new_date = datetime.now(timezone.utc).isoformat()

        collection.add(
            documents=["Old doc", "New doc"],
            ids=["old", "new"],
            metadatas=[
                {"type": "note", "repository": "test", "created_at": old_date},
                {"type": "note", "repository": "test", "created_at": new_date},
            ],
        )

        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        result = purge_by_filters(
            collection, repository="test", after_date=cutoff, dry_run=True
        )

        assert result["matched_count"] == 1
        assert "new" in result["sample_ids"]

    def test_purge_combined_filters(self, temp_chroma_client):
        """Test purging with multiple filters combined."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        collection.add(
            documents=["Match", "Wrong repo", "Wrong type", "Wrong branch"],
            ids=["match", "wrong-repo", "wrong-type", "wrong-branch"],
            metadatas=[
                {"type": "note", "repository": "my-repo", "branch": "main"},
                {"type": "note", "repository": "other-repo", "branch": "main"},
                {"type": "insight", "repository": "my-repo", "branch": "main"},
                {"type": "note", "repository": "my-repo", "branch": "feature"},
            ],
        )

        result = purge_by_filters(
            collection,
            repository="my-repo",
            branch="main",
            doc_type="note",
            dry_run=True,
        )

        assert result["matched_count"] == 1
        assert "match" in result["sample_ids"]

    def test_purge_executes_deletion(self, temp_chroma_client):
        """Test that purge actually deletes when dry_run=False."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        collection.add(
            documents=["To delete", "To keep"],
            ids=["delete-me", "keep-me"],
            metadatas=[
                {"type": "note", "repository": "purge-repo"},
                {"type": "note", "repository": "keep-repo"},
            ],
        )

        result = purge_by_filters(collection, repository="purge-repo", dry_run=False)

        assert result["matched_count"] == 1
        assert result["deleted_count"] == 1

        # Verify deletion
        deleted = collection.get(ids=["delete-me"])
        assert len(deleted["ids"]) == 0

        kept = collection.get(ids=["keep-me"])
        assert len(kept["ids"]) == 1

    def test_purge_no_matches(self, temp_chroma_client):
        """Test purge when no documents match filters."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        collection.add(
            documents=["Some doc"],
            ids=["doc1"],
            metadatas=[{"type": "note", "repository": "existing-repo"}],
        )

        result = purge_by_filters(collection, repository="nonexistent-repo", dry_run=True)

        assert result["matched_count"] == 0
        assert result["deleted_count"] == 0
        assert result["sample_ids"] == []

    def test_purge_returns_filters_applied(self, temp_chroma_client):
        """Test that purge returns the filters that were applied."""
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        result = purge_by_filters(
            collection,
            repository="my-repo",
            branch="main",
            doc_type="note",
            before_date="2024-01-01",
            after_date="2023-01-01",
            dry_run=True,
        )

        assert result["filters_applied"]["repository"] == "my-repo"
        assert result["filters_applied"]["branch"] == "main"
        assert result["filters_applied"]["doc_type"] == "note"
        assert result["filters_applied"]["before_date"] == "2024-01-01"
        assert result["filters_applied"]["after_date"] == "2023-01-01"
