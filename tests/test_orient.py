"""
Tests for orient_session tool and git staleness detection.
"""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestOrientSession:
    """Tests for orient_session tool."""

    def test_orient_unindexed_project(self, temp_git_repo: Path, temp_chroma_client):
        """Test orient_session on an unindexed project."""
        from src.tools.orient import orient_session

        with patch("src.tools.orient.orient.get_collection") as mock_collection:
            # Empty collection - no file_metadata docs
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
        assert "focused_initiative" not in result

    def test_orient_indexed_project(self, temp_git_repo: Path, temp_chroma_client):
        """Test orient_session on an indexed project."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name
        indexed_at = datetime.now(timezone.utc).isoformat()

        with patch("src.tools.orient.orient.get_collection") as mock_collection:
            # Create mock collection that responds correctly to different queries
            def mock_get(**kwargs):
                # Check for is_indexed (limit=1 file_metadata query)
                if kwargs.get("limit") == 1:
                    where = kwargs.get("where", {})
                    if isinstance(where, dict) and "$and" in where:
                        conditions = where["$and"]
                        if any(c.get("type") == "file_metadata" for c in conditions):
                            return {
                                "ids": ["file1"],
                                "documents": [],
                                "metadatas": [],
                            }

                # Check for skeleton lookup
                if "ids" in kwargs:
                    ids = kwargs["ids"]
                    if any("skeleton" in str(id) for id in ids):
                        return {
                            "ids": [f"{project_name}:skeleton:main"],
                            "documents": ["src/\n  main.py\n  utils.py"],
                            "metadatas": [{
                                "total_files": 2,
                                "total_dirs": 1,
                                "branch": "main",
                                "indexed_commit": "abc123",
                                "updated_at": indexed_at,
                            }],
                        }

                return {"ids": [], "documents": [], "metadatas": []}

            mock_collection.return_value.get.side_effect = mock_get

            result = json.loads(orient_session(str(temp_git_repo)))

        assert result["indexed"] is True
        assert result["last_indexed"] == indexed_at
        assert result["file_count"] == 2
        assert result["repository"] == project_name

    def test_orient_detects_branch_switch(self, temp_git_repo: Path):
        """Test that branch switch triggers needs_reindex."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name
        indexed_at = datetime.now(timezone.utc).isoformat()

        with patch("src.tools.orient.orient.get_collection") as mock_collection, \
             patch("src.tools.orient.orient.get_current_branch") as mock_branch:

            # Current branch is 'feature' but indexed on 'main'
            mock_branch.return_value = "feature"

            def mock_get(**kwargs):
                # is_indexed check
                if kwargs.get("limit") == 1:
                    return {"ids": ["file1"], "documents": [], "metadatas": []}

                # Skeleton lookup
                if "ids" in kwargs:
                    ids = kwargs["ids"]
                    if any("skeleton" in str(id) for id in ids):
                        return {
                            "ids": [f"{project_name}:skeleton:main"],
                            "documents": ["src/"],
                            "metadatas": [{
                                "total_files": 1,
                                "total_dirs": 1,
                                "branch": "main",  # Indexed on main
                                "indexed_commit": "abc123",
                                "updated_at": indexed_at,
                            }],
                        }

                return {"ids": [], "documents": [], "metadatas": []}

            mock_collection.return_value.get.side_effect = mock_get

            result = json.loads(orient_session(str(temp_git_repo)))

        assert result["needs_reindex"] is True
        assert "branch changed" in result["reindex_reason"].lower()

    def test_orient_detects_new_commits(self, temp_git_repo: Path):
        """Test that new commits trigger needs_reindex."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name
        indexed_at = datetime.now(timezone.utc).isoformat()

        with patch("src.tools.orient.orient.get_collection") as mock_collection, \
             patch("src.tools.orient.orient.get_commits_since") as mock_commits:

            mock_commits.return_value = 5  # 5 new commits

            def mock_get(**kwargs):
                # is_indexed check
                if kwargs.get("limit") == 1:
                    return {"ids": ["file1"], "documents": [], "metadatas": []}

                # Skeleton lookup
                if "ids" in kwargs:
                    ids = kwargs["ids"]
                    if any("skeleton" in str(id) for id in ids):
                        return {
                            "ids": [f"{project_name}:skeleton:main"],
                            "documents": ["src/"],
                            "metadatas": [{
                                "total_files": 1,
                                "total_dirs": 1,
                                "branch": "main",
                                "indexed_commit": "abc123",
                                "updated_at": indexed_at,
                            }],
                        }

                return {"ids": [], "documents": [], "metadatas": []}

            mock_collection.return_value.get.side_effect = mock_get

            result = json.loads(orient_session(str(temp_git_repo)))

        assert result["needs_reindex"] is True
        assert "5 new commit" in result["reindex_reason"]

    def test_orient_detects_file_count_change(self, temp_git_repo: Path):
        """Test that significant file count change triggers needs_reindex."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name
        indexed_at = datetime.now(timezone.utc).isoformat()

        with patch("src.tools.orient.orient.get_collection") as mock_collection, \
             patch("src.tools.orient.orient.get_commits_since") as mock_commits, \
             patch("src.tools.orient.orient.count_tracked_files") as mock_count:

            mock_commits.return_value = 0
            mock_count.return_value = 20  # Now 20 files (diff > 5 threshold)

            def mock_get(**kwargs):
                # is_indexed check
                if kwargs.get("limit") == 1:
                    return {"ids": ["file1"], "documents": [], "metadatas": []}

                # Skeleton lookup
                if "ids" in kwargs:
                    ids = kwargs["ids"]
                    if any("skeleton" in str(id) for id in ids):
                        return {
                            "ids": [f"{project_name}:skeleton:main"],
                            "documents": ["src/"],
                            "metadatas": [{
                                "total_files": 1,  # Only 1 file indexed
                                "total_dirs": 1,
                                "branch": "main",
                                "indexed_commit": "abc123",
                                "updated_at": indexed_at,
                            }],
                        }

                return {"ids": [], "documents": [], "metadatas": []}

            mock_collection.return_value.get.side_effect = mock_get

            result = json.loads(orient_session(str(temp_git_repo)))

        assert result["needs_reindex"] is True
        assert "file count changed" in result["reindex_reason"].lower()

    def test_orient_returns_skeleton_when_available(self, temp_git_repo: Path):
        """Test that skeleton is included in response when available."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name
        indexed_at = datetime.now(timezone.utc).isoformat()

        with patch("src.tools.orient.orient.get_collection") as mock_collection:

            def mock_get(**kwargs):
                # is_indexed check
                if kwargs.get("limit") == 1:
                    return {"ids": ["file1"], "documents": [], "metadatas": []}

                # Return skeleton
                if "ids" in kwargs and "skeleton" in kwargs["ids"][0]:
                    return {
                        "ids": [f"{project_name}:skeleton:main"],
                        "documents": ["src/\n  main.py\n  utils.py"],
                        "metadatas": [{
                            "total_files": 2,
                            "total_dirs": 1,
                            "branch": "main",
                            "indexed_commit": "abc123",
                            "updated_at": indexed_at,
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
        indexed_at = datetime.now(timezone.utc).isoformat()

        with patch("src.tools.orient.orient.get_collection") as mock_collection:

            def mock_get(**kwargs):
                # is_indexed check
                if kwargs.get("limit") == 1:
                    return {"ids": ["file1"], "documents": [], "metadatas": []}

                if "ids" in kwargs:
                    ids = kwargs["ids"]
                    if any("tech_stack" in id for id in ids):
                        return {
                            "ids": [f"{project_name}:tech_stack"],
                            "documents": [tech_stack_content],
                            "metadatas": [{}],
                        }
                    if any("skeleton" in id for id in ids):
                        return {
                            "ids": [f"{project_name}:skeleton:main"],
                            "documents": ["src/"],
                            "metadatas": [{
                                "total_files": 1,
                                "total_dirs": 1,
                                "branch": "main",
                                "indexed_commit": "abc123",
                                "updated_at": indexed_at,
                            }],
                        }
                return {"ids": [], "documents": [], "metadatas": []}

            mock_collection.return_value.get.side_effect = mock_get

            result = json.loads(orient_session(str(temp_git_repo)))

        assert "tech_stack" in result
        assert result["tech_stack"] == tech_stack_content

    def test_orient_returns_focused_initiative_when_set(self, temp_git_repo: Path):
        """Test that focused_initiative is included in response when set."""
        from src.tools.orient import orient_session

        project_name = temp_git_repo.name
        indexed_at = datetime.now(timezone.utc).isoformat()

        with patch("src.tools.orient.orient.get_collection") as mock_collection:

            def mock_get(**kwargs):
                # is_indexed check
                if kwargs.get("limit") == 1:
                    return {"ids": ["file1"], "documents": [], "metadatas": []}

                if "ids" in kwargs:
                    ids = kwargs["ids"]
                    # Focus document lookup
                    if any("focus" in id for id in ids):
                        return {
                            "ids": [f"{project_name}:focus"],
                            "documents": [],
                            "metadatas": [{
                                "initiative_id": "initiative:abc123",
                                "initiative_name": "Auth System Migration",
                            }],
                        }
                    # Initiative document lookup
                    if any("initiative:" in id for id in ids):
                        return {
                            "ids": ["initiative:abc123"],
                            "documents": ["Auth System Migration"],
                            "metadatas": [{
                                "name": "Auth System Migration",
                                "goal": "Migrate to JWT auth",
                                "status": "active",
                                "updated_at": indexed_at,
                            }],
                        }
                    if any("skeleton" in id for id in ids):
                        return {
                            "ids": [f"{project_name}:skeleton:main"],
                            "documents": ["src/"],
                            "metadatas": [{
                                "total_files": 1,
                                "total_dirs": 1,
                                "branch": "main",
                                "indexed_commit": "abc123",
                                "updated_at": indexed_at,
                            }],
                        }
                return {"ids": [], "documents": [], "metadatas": []}

            mock_collection.return_value.get.side_effect = mock_get

            result = json.loads(orient_session(str(temp_git_repo)))

        assert "focused_initiative" in result
        assert result["focused_initiative"]["name"] == "Auth System Migration"
        assert result["focused_initiative"]["status"] == "active"

    def test_orient_handles_error_gracefully(self, temp_git_repo: Path):
        """Test that orient_session handles errors gracefully."""
        from src.tools.orient import orient_session

        with patch("src.tools.orient.orient.get_collection") as mock_collection:
            mock_collection.side_effect = Exception("Database connection failed")

            result = json.loads(orient_session(str(temp_git_repo)))

        assert "error" in result
        assert result["indexed"] is False


class TestGitStalenessDetection:
    """Tests for git staleness detection functions."""

    def _get_head_commit(self, repo_path: Path) -> str:
        """Helper to get the current HEAD commit hash."""
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def _get_default_branch(self, repo_path: Path) -> str:
        """Helper to get the default branch name (main or master)."""
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        branch = result.stdout.strip()
        if branch:
            return branch
        # Fallback: check if main or master exists
        result = subprocess.run(
            ["git", "branch", "--list", "main"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            return "main"
        return "master"

    def test_get_commits_since(self, temp_git_repo: Path):
        """Test counting commits since a commit hash."""
        from src.external.git.detection import get_commits_since

        # Get the initial commit hash before adding new commits
        initial_commit = self._get_head_commit(temp_git_repo)

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

        count = get_commits_since(str(temp_git_repo), initial_commit)
        # Should find exactly the 3 commits we just created
        assert count == 3

    def test_get_commits_since_no_new_commits(self, temp_git_repo: Path):
        """Test counting commits when there are none since the commit."""
        from src.external.git.detection import get_commits_since

        # Get the current HEAD - there should be no commits after it
        current_commit = self._get_head_commit(temp_git_repo)

        count = get_commits_since(str(temp_git_repo), current_commit)
        assert count == 0

    def test_get_merge_commits_since(self, temp_git_repo: Path):
        """Test counting merge commits since a commit hash."""
        from src.external.git.detection import get_merge_commits_since

        # Get the commit hash before creating the merge
        before_commit = self._get_head_commit(temp_git_repo)
        default_branch = self._get_default_branch(temp_git_repo)

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
            ["git", "checkout", default_branch],
            cwd=temp_git_repo,
            capture_output=True,
        )

        subprocess.run(
            ["git", "merge", "feature", "--no-ff", "-m", "Merge feature"],
            cwd=temp_git_repo,
            capture_output=True,
        )

        count = get_merge_commits_since(str(temp_git_repo), before_commit)
        assert count >= 1

    def test_count_tracked_files(self, temp_git_repo: Path):
        """Test counting tracked files."""
        from src.external.git.detection import count_tracked_files

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
        from src.external.git.detection import count_tracked_files

        count = count_tracked_files(str(temp_dir))
        assert count == 0

    def test_get_commits_since_non_git_dir(self, temp_dir: Path):
        """Test get_commits_since returns 0 for non-git directory."""
        from src.external.git.detection import get_commits_since

        # Use a fake commit hash - should return 0 for non-git dir regardless
        count = get_commits_since(str(temp_dir), "abc123")
        assert count == 0
