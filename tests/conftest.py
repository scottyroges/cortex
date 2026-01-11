"""
Pytest fixtures for Cortex tests.
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest

# Add project root to path for src imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set test environment
os.environ["CORTEX_DB_PATH"] = "/tmp/cortex_test_db"


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_git_repo(temp_dir: Path) -> Path:
    """Create a temporary git repository."""
    import subprocess

    subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=temp_dir,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=temp_dir,
        capture_output=True,
    )

    # Create an initial commit
    test_file = temp_dir / "README.md"
    test_file.write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=temp_dir,
        capture_output=True,
    )

    return temp_dir


@pytest.fixture
def sample_python_file(temp_dir: Path) -> Path:
    """Create a sample Python file for testing."""
    file_path = temp_dir / "sample.py"
    file_path.write_text('''
def hello_world():
    """Say hello to the world."""
    print("Hello, World!")


class Calculator:
    """A simple calculator class."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def subtract(self, a: int, b: int) -> int:
        """Subtract b from a."""
        return a - b


def fibonacci(n: int) -> int:
    """Calculate the nth Fibonacci number."""
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
''')
    return file_path


@pytest.fixture
def sample_js_file(temp_dir: Path) -> Path:
    """Create a sample JavaScript file for testing."""
    file_path = temp_dir / "sample.js"
    file_path.write_text('''
function greet(name) {
    return `Hello, ${name}!`;
}

class Counter {
    constructor() {
        this.count = 0;
    }

    increment() {
        this.count++;
    }

    decrement() {
        this.count--;
    }

    getValue() {
        return this.count;
    }
}

export { greet, Counter };
''')
    return file_path


@pytest.fixture
def file_with_secrets(temp_dir: Path) -> Path:
    """Create a file containing various secrets for testing scrubbing."""
    file_path = temp_dir / "secrets.txt"
    file_path.write_text('''
# Configuration file with secrets

AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
STRIPE_KEY = "sk_test_TESTKEY1234567890abcdef"
ANTHROPIC_API_KEY = "sk-ant-api03-xxxxxxxxxxxxxxxxxxxxx"
OPENAI_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

SLACK_TOKEN = "xoxb-123456789-abcdefghijk"

-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF8PbnGy
-----END RSA PRIVATE KEY-----

Normal text that should not be redacted.
API_URL = "https://api.example.com"
''')
    return file_path


@pytest.fixture
def temp_chroma_client():
    """Create a temporary ChromaDB client for testing."""
    import chromadb
    from chromadb.config import Settings

    with tempfile.TemporaryDirectory() as tmpdir:
        client = chromadb.PersistentClient(
            path=tmpdir,
            settings=Settings(anonymized_telemetry=False),
        )
        yield client
