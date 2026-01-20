"""
Cortex Ignore Patterns

Default patterns and loading logic for cortexignore files.
Follows .gitignore-style format for filtering files during indexing.
"""

from pathlib import Path

from src.configs.paths import ensure_data_dir

# --- Default Ignore Patterns ---
# Hardcoded sensible defaults for all projects

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

# --- Global Cortexignore Template ---
# Created at ~/.cortex/cortexignore on first use

GLOBAL_CORTEXIGNORE_TEMPLATE = """\
# Cortex global ignore patterns
# These apply to all projects. Edit as needed.

# Large data files
*.csv
*.parquet
*.pkl
*.h5
*.hdf5

# ML/AI artifacts
*.pt
*.pth
*.onnx
*.safetensors
checkpoints/
wandb/
mlruns/

# Logs and databases
*.log
*.sqlite
*.db

# OS files
.DS_Store
Thumbs.db

# Archives
*.zip
*.tar
*.tar.gz
*.tgz

# Lock files
package-lock.json
yarn.lock
pnpm-lock.yaml
poetry.lock
Cargo.lock
Gemfile.lock
"""


def _load_ignore_file(path: Path) -> set[str]:
    """Load patterns from an ignore file (like .gitignore format)."""
    if not path.exists():
        return set()
    patterns = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.add(line)
    return patterns


def load_ignore_patterns(root_path: str, use_cortexignore: bool = True) -> set[str]:
    """Load and merge ignore patterns from global + project cortexignore files.

    Merge order (all patterns combined):
    1. DEFAULT_IGNORE_PATTERNS (hardcoded sensible defaults)
    2. Global ~/.cortex/cortexignore (user's smart defaults)
    3. Project <root>/.cortexignore (project-specific)

    Args:
        root_path: Root path of the project being indexed
        use_cortexignore: If False, only return DEFAULT_IGNORE_PATTERNS

    Returns:
        Set of ignore patterns to use for filtering
    """
    patterns = set(DEFAULT_IGNORE_PATTERNS)

    if not use_cortexignore:
        return patterns

    # Global: ~/.cortex/cortexignore (created with defaults if not exists)
    global_ignore = ensure_data_dir() / "cortexignore"
    patterns.update(_load_ignore_file(global_ignore))

    # Project: <root>/.cortexignore
    project_ignore = Path(root_path) / ".cortexignore"
    patterns.update(_load_ignore_file(project_ignore))

    return patterns
