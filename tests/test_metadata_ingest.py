"""
Tests for Metadata-First Ingestion

Tests the new metadata-based ingestion that replaces code chunking.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

from src.ingest.metadata import (
    ingest_file_metadata,
    build_dependencies,
    MetadataIngestionResult,
    _resolve_import,
)


class TestMetadataIngestion:
    """Test metadata-based file ingestion."""

    @pytest.fixture
    def mock_collection(self):
        """Create a mock ChromaDB collection."""
        collection = Mock()
        collection.upsert = Mock()
        return collection

    @pytest.fixture
    def temp_python_file(self):
        """Create a temporary Python file for testing."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write('''
"""User authentication module."""

from typing import Optional
from .models import User

class AuthService:
    """Handles user authentication."""

    def authenticate(self, username: str, password: str) -> Optional[str]:
        """Authenticate user and return token."""
        pass

    def verify_token(self, token: str) -> bool:
        """Verify a JWT token."""
        pass
''')
            f.flush()
            yield Path(f.name)
        os.unlink(f.name)

    def test_ingest_python_file(self, mock_collection, temp_python_file):
        """Test ingesting a Python file creates correct documents."""
        result = ingest_file_metadata(
            file_path=temp_python_file,
            collection=mock_collection,
            repo_id="test-repo",
            branch="main",
        )

        assert result.error is None
        assert result.file_metadata_id is not None
        assert "test-repo:file:" in result.file_metadata_id
        assert result.metadata is not None
        assert result.metadata.language == "python"
        assert len(result.metadata.classes) == 1
        assert result.metadata.classes[0].name == "AuthService"

        # Should have called upsert for file_metadata
        mock_collection.upsert.assert_called()

    def test_ingest_empty_file(self, mock_collection):
        """Test that empty files are skipped."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("")  # Empty file
            f.flush()
            path = Path(f.name)

        try:
            result = ingest_file_metadata(
                file_path=path,
                collection=mock_collection,
                repo_id="test-repo",
                branch="main",
            )

            assert result.error == "Empty file"
            assert result.file_metadata_id is None
        finally:
            os.unlink(str(path))

    def test_ingest_unsupported_language(self, mock_collection):
        """Test that unsupported languages are skipped."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".go", delete=False
        ) as f:
            f.write("package main\nfunc main() {}")
            f.flush()
            path = Path(f.name)

        try:
            result = ingest_file_metadata(
                file_path=path,
                collection=mock_collection,
                repo_id="test-repo",
                branch="main",
            )

            assert "Unsupported" in result.error
        finally:
            os.unlink(str(path))

    def test_ingest_with_data_contract(self, mock_collection):
        """Test that data contracts are extracted and stored."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write('''
from dataclasses import dataclass

@dataclass
class User:
    name: str
    email: str
    age: int = 0
''')
            f.flush()
            path = Path(f.name)

        try:
            result = ingest_file_metadata(
                file_path=path,
                collection=mock_collection,
                repo_id="test-repo",
                branch="main",
            )

            assert result.error is None
            assert len(result.data_contract_ids) == 1
            assert "contract" in result.data_contract_ids[0]
        finally:
            os.unlink(str(path))

    def test_ingest_with_entry_point(self, mock_collection):
        """Test that entry points are detected and stored."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write('''
def main():
    print("Hello")

if __name__ == "__main__":
    main()
''')
            f.flush()
            path = Path(f.name)

        try:
            result = ingest_file_metadata(
                file_path=path,
                collection=mock_collection,
                repo_id="test-repo",
                branch="main",
            )

            assert result.error is None
            assert result.entry_point_id is not None
            assert "entry" in result.entry_point_id
        finally:
            os.unlink(str(path))


class TestImportResolution:
    """Test import path resolution."""

    def test_resolve_relative_import(self):
        """Test resolving relative imports."""
        all_files = {
            "src/auth/service.py",
            "src/auth/models.py",
            "src/auth/__init__.py",
        }

        resolved = _resolve_import(
            ".models",
            "src/auth/service.py",
            all_files,
        )

        assert resolved == "src/auth/models.py"

    def test_resolve_absolute_import(self):
        """Test resolving absolute imports."""
        all_files = {
            "src/utils.py",
            "src/auth/service.py",
        }

        resolved = _resolve_import(
            "src.utils",
            "src/auth/service.py",
            all_files,
        )

        assert resolved == "src/utils.py"

    def test_resolve_unknown_import(self):
        """Test that unknown imports return None."""
        all_files = {"src/auth/service.py"}

        resolved = _resolve_import(
            "unknown.module",
            "src/auth/service.py",
            all_files,
        )

        assert resolved is None


class TestDependencyBuilding:
    """Test dependency document building."""

    @pytest.fixture
    def mock_collection(self):
        collection = Mock()
        collection.upsert = Mock()
        return collection

    def test_build_dependencies(self, mock_collection):
        """Test building dependency documents."""
        from src.ast.models import FileMetadata, ImportInfo

        # Create mock results with imports
        result1 = MetadataIngestionResult(
            file_path="src/service.py",
            file_metadata_id="test:file:src/service.py",
            metadata=FileMetadata(
                file_path="src/service.py",
                language="python",
                imports=[
                    ImportInfo(module=".models", is_external=False),
                    ImportInfo(module="requests", is_external=True),
                ],
            ),
        )

        result2 = MetadataIngestionResult(
            file_path="src/models.py",
            file_metadata_id="test:file:src/models.py",
            metadata=FileMetadata(
                file_path="src/models.py",
                language="python",
                imports=[],
            ),
        )

        count = build_dependencies(
            results=[result1, result2],
            collection=mock_collection,
            repo_id="test-repo",
            branch="main",
        )

        # Should create dependency documents
        assert mock_collection.upsert.called


class TestStoredDocumentContent:
    """Test the content and metadata of stored documents."""

    @pytest.fixture
    def mock_collection(self):
        collection = Mock()
        collection.upsert = Mock()
        return collection

    def test_file_metadata_content(self, mock_collection):
        """Test that file_metadata documents have correct content."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write('''
"""Authentication service."""

def authenticate(user: str, password: str) -> bool:
    """Check credentials."""
    return True

def logout(user: str) -> None:
    """Log out user."""
    pass
''')
            f.flush()
            path = Path(f.name)

        try:
            result = ingest_file_metadata(
                file_path=path,
                collection=mock_collection,
                repo_id="test-repo",
                branch="main",
            )

            # Check upsert was called with correct structure
            calls = mock_collection.upsert.call_args_list
            assert len(calls) >= 1

            # First call should be file_metadata
            first_call = calls[0]
            meta = first_call.kwargs.get("metadatas", first_call[1].get("metadatas"))[0]

            assert meta["type"] == "file_metadata"
            assert meta["repository"] == "test-repo"
            assert meta["branch"] == "main"
            assert meta["language"] == "python"
            assert "authenticate" in meta["exports"]
        finally:
            os.unlink(str(path))
