"""
Tests for orient_session tool and git staleness detection.
"""

import json
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


class TestOrientSession:
    """Tests for orient_session tool."""

    def test_orient_unindexed_project(self, temp_git_repo: Path, temp_chroma_client):
        """Test orient_session on an unindexed project."""
        from src.tools.orient import orient_session

        with patch("src.tools.orient.get_collection") as mock_collection, \
             patch("src.tools.orient.load_state") as mock_load_state:

            # Empty state - not indexed
            mock_load_state.return_value = {}

            # Empty collection
            mock_collection.return_value.get.return_value = {
                "ids": [],
                "documents": [],
                "metadatas": [],
            }

            result = json.loads(orient_session(str(temp_git_repo)))

        assert result["indexed"] is False
        assert result["last_indexed"] == "never"
        assert result["file_count"] == 0
        assert result["needs_reindex"] is False
        assert "skeleton" not in result
        assert "tech_stack" not in result
        assert "active_initiative" not in result

    def test_orient_indexed_project(self, temp_git_repo: Path, temp_chroma_client):
        """Test orient_session on an indexed project."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name
        indexed_at = datetime.now(timezone.utc).isoformat()

        with patch("src.tools.orient.get_collection") as mock_collection, \
             patch("src.tools.orient.load_state") as mock_load_state:

            # State shows indexed
            mock_load_state.return_value = {
                "project": project_name,
                "indexed_commit": "abc123",
                "indexed_at": indexed_at,
                "branch": "main",
                "file_hashes": {"file1.py": "hash1", "file2.py": "hash2"},
            }

            # Empty collection for skeleton/context lookups
            mock_collection.return_value.get.return_value = {
                "ids": [],
                "documents": [],
                "metadatas": [],
            }

            result = json.loads(orient_session(str(temp_git_repo)))

        assert result["indexed"] is True
        assert result["last_indexed"] == indexed_at
        assert result["file_count"] == 2
        assert result["project"] == project_name

    def test_orient_detects_branch_switch(self, temp_git_repo: Path):
        """Test that branch switch triggers needs_reindex."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name
        indexed_at = datetime.now(timezone.utc).isoformat()

        with patch("src.tools.orient.get_collection") as mock_collection, \
             patch("src.tools.orient.load_state") as mock_load_state, \
             patch("src.tools.orient.get_current_branch") as mock_branch:

            # Indexed on 'main', but now on 'feature'
            mock_load_state.return_value = {
                "project": project_name,
                "indexed_commit": "abc123",
                "indexed_at": indexed_at,
                "branch": "main",
                "file_hashes": {"file1.py": "hash1"},
            }
            mock_branch.return_value = "feature"

            mock_collection.return_value.get.return_value = {
                "ids": [],
                "documents": [],
                "metadatas": [],
            }

            result = json.loads(orient_session(str(temp_git_repo)))

        assert result["needs_reindex"] is True
        assert "branch changed" in result["reindex_reason"].lower()

    def test_orient_detects_new_commits(self, temp_git_repo: Path):
        """Test that new commits trigger needs_reindex."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name
        indexed_at = datetime.now(timezone.utc).isoformat()

        with patch("src.tools.orient.get_collection") as mock_collection, \
             patch("src.tools.orient.load_state") as mock_load_state, \
             patch("src.tools.orient.get_commits_since") as mock_commits:

            mock_load_state.return_value = {
                "project": project_name,
                "indexed_commit": "abc123",
                "indexed_at": indexed_at,
                "branch": "main",
                "file_hashes": {"file1.py": "hash1"},
            }
            mock_commits.return_value = 5  # 5 new commits

            mock_collection.return_value.get.return_value = {
                "ids": [],
                "documents": [],
                "metadatas": [],
            }

            result = json.loads(orient_session(str(temp_git_repo)))

        assert result["needs_reindex"] is True
        assert "5 new commit" in result["reindex_reason"]

    def test_orient_detects_file_count_change(self, temp_git_repo: Path):
        """Test that significant file count change triggers needs_reindex."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name
        indexed_at = datetime.now(timezone.utc).isoformat()

        with patch("src.tools.orient.get_collection") as mock_collection, \
             patch("src.tools.orient.load_state") as mock_load_state, \
             patch("src.tools.orient.get_commits_since") as mock_commits, \
             patch("src.tools.orient.count_tracked_files") as mock_count:

            mock_load_state.return_value = {
                "project": project_name,
                "indexed_commit": "abc123",
                "indexed_at": indexed_at,
                "branch": "main",
                "file_hashes": {"file1.py": "hash1"},  # 1 file indexed
            }
            mock_commits.return_value = 0
            mock_count.return_value = 20  # Now 20 files (diff > 5 threshold)

            mock_collection.return_value.get.return_value = {
                "ids": [],
                "documents": [],
                "metadatas": [],
            }

            result = json.loads(orient_session(str(temp_git_repo)))

        assert result["needs_reindex"] is True
        assert "file count changed" in result["reindex_reason"].lower()

    def test_orient_returns_skeleton_when_available(self, temp_git_repo: Path):
        """Test that skeleton is included in response when available."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name

        with patch("src.tools.orient.get_collection") as mock_collection, \
             patch("src.tools.orient.load_state") as mock_load_state:

            mock_load_state.return_value = {
                "project": project_name,
                "indexed_commit": "abc123",
                "indexed_at": datetime.now(timezone.utc).isoformat(),
                "branch": "main",
                "file_hashes": {},
            }

            # Return skeleton on first call
            def mock_get(**kwargs):
                if "ids" in kwargs and "skeleton" in kwargs["ids"][0]:
                    return {
                        "ids": [f"{project_name}:skeleton:main"],
                        "documents": ["src/\n  main.py\n  utils.py"],
                        "metadatas": [{
                            "total_files": 2,
                            "total_dirs": 1,
                            "branch": "main",
                        }],
                    }
                return {"ids": [], "documents": [], "metadatas": []}

            mock_collection.return_value.get.side_effect = mock_get

            result = json.loads(orient_session(str(temp_git_repo)))

        assert "skeleton" in result
        assert result["skeleton"]["total_files"] == 2
        assert result["skeleton"]["total_dirs"] == 1

    def test_orient_returns_tech_stack_when_set(self, temp_git_repo: Path):
        """Test that tech_stack is included in response when set."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name
        tech_stack_content = "Python, FastAPI, PostgreSQL"

        with patch("src.tools.orient.get_collection") as mock_collection, \
             patch("src.tools.orient.load_state") as mock_load_state:

            mock_load_state.return_value = {
                "project": project_name,
                "indexed_commit": "abc123",
                "indexed_at": datetime.now(timezone.utc).isoformat(),
                "branch": "main",
                "file_hashes": {},
            }

            call_count = [0]

            def mock_get(**kwargs):
                call_count[0] += 1
                if "ids" in kwargs:
                    ids = kwargs["ids"]
                    if any("tech_stack" in id for id in ids):
                        return {
                            "ids": [f"{project_name}:tech_stack"],
                            "documents": [tech_stack_content],
                            "metadatas": [{}],
                        }
                return {"ids": [], "documents": [], "metadatas": []}

            mock_collection.return_value.get.side_effect = mock_get

            result = json.loads(orient_session(str(temp_git_repo)))

        assert "tech_stack" in result
        assert result["tech_stack"] == tech_stack_content

    def test_orient_returns_initiative_when_set(self, temp_git_repo: Path):
        """Test that active_initiative is included in response when set."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name

        with patch("src.tools.orient.get_collection") as mock_collection, \
             patch("src.tools.orient.load_state") as mock_load_state:

            mock_load_state.return_value = {
                "project": project_name,
                "indexed_commit": "abc123",
                "indexed_at": datetime.now(timezone.utc).isoformat(),
                "branch": "main",
                "file_hashes": {},
            }

            def mock_get(**kwargs):
                if "ids" in kwargs:
                    ids = kwargs["ids"]
                    if any("initiative" in id for id in ids):
                        return {
                            "ids": [f"{project_name}:initiative"],
                            "documents": ["Auth System Migration"],
                            "metadatas": [{
                                "initiative_name": "Auth System Migration",
                                "initiative_status": "Phase 2: In Progress",
                            }],
                        }
                return {"ids": [], "documents": [], "metadatas": []}

            mock_collection.return_value.get.side_effect = mock_get

            result = json.loads(orient_session(str(temp_git_repo)))

        assert "active_initiative" in result
        assert result["active_initiative"]["name"] == "Auth System Migration"
        assert result["active_initiative"]["status"] == "Phase 2: In Progress"

    def test_orient_handles_error_gracefully(self, temp_git_repo: Path):
        """Test that orient_session handles errors gracefully."""
        from src.tools.orient import orient_session

        with patch("src.tools.orient.get_collection") as mock_collection:
            mock_collection.side_effect = Exception("Database connection failed")

            result = json.loads(orient_session(str(temp_git_repo)))

        assert "error" in result
        assert result["indexed"] is False


class TestGitStalenessDetection:
    """Tests for git staleness detection functions."""

    def test_get_commits_since(self, temp_git_repo: Path):
        """Test counting commits since timestamp."""
        from src.git.detection import get_commits_since

        # Get count before adding new commits
        initial_time = datetime.now(timezone.utc).isoformat()
        time.sleep(1)  # Git timestamp resolution is 1 second

        # Create some commits
        for i in range(3):
            test_file = temp_git_repo / f"file{i}.txt"
            test_file.write_text(f"content {i}")
            subprocess.run(["git", "add", "."], cwd=temp_git_repo, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", f"Commit {i}"],
                cwd=temp_git_repo,
                capture_output=True,
            )

        count = get_commits_since(str(temp_git_repo), initial_time)
        # Should find at least the 3 commits we just created
        assert count >= 3

    def test_get_commits_since_no_new_commits(self, temp_git_repo: Path):
        """Test counting commits when there are none since timestamp."""
        from src.git.detection import get_commits_since

        # Wait 1 second (git timestamp resolution) then record time
        time.sleep(1)
        after_time = datetime.now(timezone.utc).isoformat()

        count = get_commits_since(str(temp_git_repo), after_time)
        assert count == 0

    def test_get_merge_commits_since(self, temp_git_repo: Path):
        """Test counting merge commits since timestamp."""
        from src.git.detection import get_merge_commits_since

        before_time = datetime.now(timezone.utc).isoformat()
        time.sleep(0.1)

        # Create a branch and merge it
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=temp_git_repo,
            capture_output=True,
        )
        test_file = temp_git_repo / "feature.txt"
        test_file.write_text("feature content")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Feature commit"],
            cwd=temp_git_repo,
            capture_output=True,
        )

        subprocess.run(
            ["git", "checkout", "main"],
            cwd=temp_git_repo,
            capture_output=True,
        )
        # Use fallback branch name if main doesn't exist
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )
        if "main" not in result.stdout and "master" not in result.stdout:
            subprocess.run(
                ["git", "checkout", "master"],
                cwd=temp_git_repo,
                capture_output=True,
            )

        subprocess.run(
            ["git", "merge", "feature", "--no-ff", "-m", "Merge feature"],
            cwd=temp_git_repo,
            capture_output=True,
        )

        count = get_merge_commits_since(str(temp_git_repo), before_time)
        assert count >= 1

    def test_count_tracked_files(self, temp_git_repo: Path):
        """Test counting tracked files."""
        from src.git.detection import count_tracked_files

        # Initial repo has README.md
        initial_count = count_tracked_files(str(temp_git_repo))
        assert initial_count >= 1

        # Add more files
        for i in range(5):
            test_file = temp_git_repo / f"new_file{i}.txt"
            test_file.write_text(f"content {i}")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add files"],
            cwd=temp_git_repo,
            capture_output=True,
        )

        new_count = count_tracked_files(str(temp_git_repo))
        assert new_count == initial_count + 5

    def test_count_tracked_files_non_git_dir(self, temp_dir: Path):
        """Test count_tracked_files returns 0 for non-git directory."""
        from src.git.detection import count_tracked_files

        count = count_tracked_files(str(temp_dir))
        assert count == 0

    def test_get_commits_since_non_git_dir(self, temp_dir: Path):
        """Test get_commits_since returns 0 for non-git directory."""
        from src.git.detection import get_commits_since

        count = get_commits_since(str(temp_dir), datetime.now(timezone.utc).isoformat())
        assert count == 0
