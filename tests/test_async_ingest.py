"""
Tests for async ingestion functionality.
"""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tools.ingest.async_processor import (
    IngestionTask,
    IngestionTaskStore,
    IngestionWorker,
    create_task,
)


# =============================================================================
# IngestionTask Tests
# =============================================================================


class TestIngestionTask:
    """Tests for IngestionTask dataclass."""

    def test_create_task(self):
        """Test task creation with create_task helper."""
        task = create_task(
            path="/test/path",
            repository="test-repo",
            force_full=True,
        )

        assert task.task_id.startswith("ingest:")
        assert task.repository == "test-repo"
        assert task.path == "/test/path"
        assert task.status == "pending"
        assert task.force_full is True
        assert task.files_total == 0
        assert task.files_processed == 0

    def test_to_dict_and_from_dict(self):
        """Test serialization/deserialization."""
        task = create_task(
            path="/test/path",
            repository="test-repo",
            force_full=False,
            include_patterns=["src/**"],
            files_total=100,
        )
        task.files_processed = 50
        task.docs_created = 150

        # Serialize
        data = task.to_dict()
        assert data["repository"] == "test-repo"
        assert data["files_processed"] == 50

        # Deserialize
        restored = IngestionTask.from_dict(data)
        assert restored.task_id == task.task_id
        assert restored.files_processed == 50
        assert restored.include_patterns == ["src/**"]


# =============================================================================
# IngestionTaskStore Tests
# =============================================================================


class TestIngestionTaskStore:
    """Tests for IngestionTaskStore persistence."""

    @pytest.fixture
    def temp_store(self, tmp_path):
        """Create a store with a temporary file."""
        store = IngestionTaskStore()
        store._file_path = tmp_path / "ingest_tasks.json"
        return store

    def test_create_and_get_task(self, temp_store):
        """Test creating and retrieving a task."""
        task = create_task(
            path="/test/path",
            repository="test-repo",
        )

        temp_store.create_task(task)
        retrieved = temp_store.get_task(task.task_id)

        assert retrieved is not None
        assert retrieved.task_id == task.task_id
        assert retrieved.repository == "test-repo"

    def test_get_nonexistent_task(self, temp_store):
        """Test getting a task that doesn't exist."""
        result = temp_store.get_task("nonexistent-id")
        assert result is None

    def test_update_progress(self, temp_store):
        """Test updating task progress."""
        task = create_task(path="/test", repository="test-repo")
        temp_store.create_task(task)

        temp_store.update_progress(task.task_id, 50, 100, 150)

        retrieved = temp_store.get_task(task.task_id)
        assert retrieved.files_processed == 50
        assert retrieved.files_total == 100
        assert retrieved.docs_created == 150

    def test_complete_task(self, temp_store):
        """Test marking a task as completed."""
        task = create_task(path="/test", repository="test-repo")
        temp_store.create_task(task)

        result = {"files_processed": 100, "docs_created": 300}
        temp_store.complete_task(task.task_id, result)

        retrieved = temp_store.get_task(task.task_id)
        assert retrieved.status == "completed"
        assert retrieved.result == result
        assert retrieved.completed_at is not None

    def test_fail_task(self, temp_store):
        """Test marking a task as failed."""
        task = create_task(path="/test", repository="test-repo")
        temp_store.create_task(task)

        temp_store.fail_task(task.task_id, "Something went wrong")

        retrieved = temp_store.get_task(task.task_id)
        assert retrieved.status == "failed"
        assert retrieved.error == "Something went wrong"

    def test_active_task_for_repo(self, temp_store):
        """Test detecting active tasks for a repository."""
        task = create_task(path="/test", repository="test-repo")
        temp_store.create_task(task)

        # Should find the active task
        active = temp_store.get_active_task_for_repo("test-repo")
        assert active is not None
        assert active.task_id == task.task_id

        # Complete it
        temp_store.complete_task(task.task_id, {})

        # Should no longer find it
        active = temp_store.get_active_task_for_repo("test-repo")
        assert active is None

    def test_conflict_detection(self, temp_store):
        """Test that creating a task for a repo with active task fails."""
        task1 = create_task(path="/test1", repository="test-repo")
        temp_store.create_task(task1)

        task2 = create_task(path="/test2", repository="test-repo")
        with pytest.raises(ValueError, match="already in progress"):
            temp_store.create_task(task2)

    def test_get_pending_tasks(self, temp_store):
        """Test getting all pending tasks."""
        task1 = create_task(path="/test1", repository="repo1")
        task2 = create_task(path="/test2", repository="repo2")

        temp_store.create_task(task1)
        temp_store.create_task(task2)

        pending = temp_store.get_pending_tasks()
        assert len(pending) == 2

        # Complete one
        temp_store.complete_task(task1.task_id, {})
        pending = temp_store.get_pending_tasks()
        assert len(pending) == 1
        assert pending[0].task_id == task2.task_id

    def test_get_all_tasks_with_filter(self, temp_store):
        """Test getting tasks filtered by repository."""
        task1 = create_task(path="/test1", repository="repo1")
        task2 = create_task(path="/test2", repository="repo2")

        temp_store.create_task(task1)
        temp_store.create_task(task2)

        # Get all
        all_tasks = temp_store.get_all_tasks()
        assert len(all_tasks) == 2

        # Filter by repo
        repo1_tasks = temp_store.get_all_tasks(repository="repo1")
        assert len(repo1_tasks) == 1
        assert repo1_tasks[0].repository == "repo1"


# =============================================================================
# IngestionWorker Tests
# =============================================================================


class TestIngestionWorker:
    """Tests for IngestionWorker."""

    @pytest.fixture
    def worker(self, tmp_path):
        """Create a worker with a temporary store."""
        worker = IngestionWorker()
        worker._store._file_path = tmp_path / "ingest_tasks.json"
        return worker

    def test_queue_task(self, worker):
        """Test queueing a task."""
        task = create_task(path="/test", repository="test-repo")
        task_id = worker.queue_task(task)

        assert task_id == task.task_id

        # Should be able to get status
        status = worker.get_status(task_id)
        assert status is not None
        assert status["status"] == "pending"

    def test_get_status_not_found(self, worker):
        """Test getting status of nonexistent task."""
        status = worker.get_status("nonexistent-id")
        assert status is None

    def test_get_status_format(self, worker):
        """Test status response format."""
        task = create_task(
            path="/test",
            repository="test-repo",
            force_full=True,
            files_total=100,
        )
        worker.queue_task(task)

        status = worker.get_status(task.task_id)

        assert "task_id" in status
        assert "repository" in status
        assert "status" in status
        assert "progress" in status
        assert "timing" in status

        assert status["progress"]["files_total"] == 100
        assert status["progress"]["percent"] == 0


# =============================================================================
# Integration Tests
# =============================================================================


class TestAsyncIngestIntegration:
    """Integration tests for async ingestion."""

    def test_sync_vs_async_decision_small_delta(self, tmp_path):
        """Test that small delta uses sync mode."""
        from src.tools.ingest import ASYNC_FILE_THRESHOLD

        # Create a small test repo
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "test.py").write_text("# test")

        # Mock the delta strategy to return few files
        with patch("src.tools.ingest.ingest.select_delta_strategy") as mock_strategy:
            mock_result = MagicMock()
            mock_result.files_to_process = [tmp_path / "src/test.py"]  # 1 file
            mock_strategy.return_value.get_files_to_process.return_value = mock_result

            # Mock get_collection to avoid ChromaDB connection
            with patch("src.tools.ingest.ingest.get_collection") as mock_collection:
                mock_collection.return_value = MagicMock()

                with patch("src.tools.ingest.ingest._run_sync_ingestion") as mock_sync:
                    mock_sync.return_value = json.dumps({"status": "success"})

                    from src.tools.ingest.ingest import ingest_code_into_cortex

                    # This should use sync mode (1 file < 50)
                    result = ingest_code_into_cortex(str(tmp_path))

                    mock_sync.assert_called_once()

    def test_sync_vs_async_decision_large_delta(self, tmp_path):
        """Test that large delta uses async mode."""
        from src.tools.ingest import ASYNC_FILE_THRESHOLD

        # Mock the delta strategy to return many files
        with patch("src.tools.ingest.ingest.select_delta_strategy") as mock_strategy:
            mock_result = MagicMock()
            # Create list of 60 mock files (> 50 threshold)
            mock_result.files_to_process = [tmp_path / f"file{i}.py" for i in range(60)]
            mock_strategy.return_value.get_files_to_process.return_value = mock_result

            # Mock get_collection to avoid ChromaDB connection
            with patch("src.tools.ingest.ingest.get_collection") as mock_collection:
                mock_collection.return_value = MagicMock()

                with patch("src.tools.ingest.ingest._queue_async_ingestion") as mock_async:
                    mock_async.return_value = json.dumps({"status": "queued", "task_id": "test"})

                    from src.tools.ingest.ingest import ingest_code_into_cortex

                    # This should use async mode (60 files >= 50)
                    result = ingest_code_into_cortex(str(tmp_path))

                    mock_async.assert_called_once()

    def test_force_full_always_async(self, tmp_path):
        """Test that force_full=True always uses async mode."""
        with patch("src.tools.ingest.ingest._queue_async_ingestion") as mock_async:
            mock_async.return_value = json.dumps({"status": "queued", "task_id": "test"})

            from src.tools.ingest.ingest import ingest_code_into_cortex

            result = ingest_code_into_cortex(str(tmp_path), force_full=True)

            mock_async.assert_called_once()
            # Check that force_full was passed
            call_kwargs = mock_async.call_args.kwargs
            assert call_kwargs["force_full"] is True
