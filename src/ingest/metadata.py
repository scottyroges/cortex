"""
Metadata-First Ingestion

Ingests source files as structured metadata instead of raw code chunks.
Creates file_metadata, data_contract, entry_point, and dependency documents.

Document types defined in src.documents:
- file_metadata: Primary search anchor for each file
- data_contract: Interfaces, types, schemas
- entry_point: Main functions, API routes, CLI entry points
- dependency: Import relationships (forward and reverse)

Philosophy: "Code can be grepped. Understanding cannot."
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

import chromadb

from logging_config import get_logger
from src.ast.parser import get_parser
from src.ast.extractors import get_extractor  # Import from package to trigger registration
from src.ast.description import generate_description_from_metadata
from src.ast.models import DataContractInfo, FileMetadata
from src.ingest.walker import compute_file_hash
from src.llm import LLMProvider
from src.security import scrub_secrets

if TYPE_CHECKING:
    from src.documents import (
        FileMetadataDoc,
        DataContractDoc,
        EntryPointDoc,
        DependencyDoc,
    )

logger = get_logger("ingest.metadata")


@dataclass
class MetadataIngestionResult:
    """Result from ingesting a single file as metadata."""

    file_path: str
    file_metadata_id: Optional[str] = None
    data_contract_ids: list[str] = field(default_factory=list)
    entry_point_id: Optional[str] = None
    metadata: Optional[FileMetadata] = None
    error: Optional[str] = None


def ingest_file_metadata(
    file_path: Path,
    collection: chromadb.Collection,
    repo_id: str,
    branch: str,
    llm_provider: Optional[LLMProvider] = None,
) -> MetadataIngestionResult:
    """
    Ingest a single file as structured metadata.

    Creates:
    - file_metadata document (always)
    - data_contract documents (for each interface/type/schema)
    - entry_point document (if file is an entry point)

    Args:
        file_path: Path to the source file
        collection: ChromaDB collection
        repo_id: Repository identifier
        branch: Git branch name
        llm_provider: Optional LLM provider for descriptions

    Returns:
        MetadataIngestionResult with created document IDs
    """
    result = MetadataIngestionResult(file_path=str(file_path))

    # Read and validate file
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, IOError) as e:
        result.error = f"Read error: {e}"
        logger.debug(f"Skipped (read error): {file_path}")
        return result

    if not content.strip():
        result.error = "Empty file"
        logger.debug(f"Skipped (empty): {file_path}")
        return result

    # Scrub secrets
    content = scrub_secrets(content)

    # Get parser and extractor
    parser = get_parser()
    language = parser.detect_language(str(file_path))

    if language is None:
        result.error = f"Unsupported language"
        logger.debug(f"Skipped (unsupported): {file_path}")
        return result

    extractor = get_extractor(language)
    if extractor is None:
        result.error = f"No extractor for {language}"
        logger.debug(f"Skipped (no extractor): {file_path}")
        return result

    # Parse and extract metadata
    tree = parser.parse(content, language)
    if tree is None:
        result.error = "Parse failed"
        logger.debug(f"Skipped (parse failed): {file_path}")
        return result

    metadata = extractor.extract_all(tree, content, str(file_path))
    metadata.file_hash = compute_file_hash(file_path)
    result.metadata = metadata

    # Generate LLM description
    if llm_provider:
        metadata.description = generate_description_from_metadata(
            metadata, content, provider=llm_provider
        )
    else:
        # Fallback description
        exports = metadata.get_export_list()
        if exports:
            metadata.description = f"{file_path} - {language} file with: {', '.join(exports[:5])}"
        else:
            metadata.description = f"{file_path} - {language} file"

    now = datetime.now(timezone.utc).isoformat()

    # Store file_metadata document
    file_meta_id = _store_file_metadata(
        collection, metadata, repo_id, branch, now
    )
    result.file_metadata_id = file_meta_id

    # Store data_contract documents
    for contract in metadata.data_contracts:
        contract_id = _store_data_contract(
            collection, contract, str(file_path), repo_id, branch, language, now
        )
        result.data_contract_ids.append(contract_id)

    # Store entry_point document if applicable
    if metadata.is_entry_point:
        entry_id = _store_entry_point(
            collection, metadata, repo_id, branch, now
        )
        result.entry_point_id = entry_id

    logger.debug(
        f"Ingested: {file_path.name} ({language}) - "
        f"1 file_metadata, {len(result.data_contract_ids)} contracts, "
        f"{'1 entry_point' if result.entry_point_id else '0 entry_points'}"
    )

    return result


def _store_file_metadata(
    collection: chromadb.Collection,
    metadata: FileMetadata,
    repo_id: str,
    branch: str,
    timestamp: str,
) -> str:
    """Store a file_metadata document."""
    doc_id = f"{repo_id}:file:{metadata.file_path}"

    # Build searchable content
    content = metadata.to_search_content()

    # Build metadata dict
    meta = {
        "type": "file_metadata",
        "file_path": metadata.file_path,
        "repository": repo_id,
        "branch": branch,
        "language": metadata.language,
        "description": metadata.description,
        "exports": ",".join(metadata.get_export_list()[:20]),
        "is_entry_point": metadata.is_entry_point,
        "is_barrel": metadata.is_barrel,
        "is_test": metadata.is_test,
        "is_config": metadata.is_config,
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    # Add optional fields
    if metadata.entry_point_type:
        meta["entry_point_type"] = metadata.entry_point_type
    if metadata.file_hash:
        meta["file_hash"] = metadata.file_hash

    collection.upsert(
        ids=[doc_id],
        documents=[content],
        metadatas=[meta],
    )

    return doc_id


def _store_data_contract(
    collection: chromadb.Collection,
    contract: DataContractInfo,
    file_path: str,
    repo_id: str,
    branch: str,
    language: str,
    timestamp: str,
) -> str:
    """Store a data_contract document."""
    doc_id = f"{repo_id}:contract:{file_path}:{contract.name}"

    # Build searchable content - include the source text
    content_parts = [
        contract.name,
        file_path,
    ]

    if contract.source_text:
        content_parts.append(contract.source_text)

    # Add field info
    if contract.fields:
        field_desc = ", ".join(f"{f.name}: {f.type_annotation}" for f in contract.fields[:10])
        content_parts.append(f"Fields: {field_desc}")

    content = "\n\n".join(content_parts)

    # Build metadata
    meta = {
        "type": "data_contract",
        "name": contract.name,
        "file_path": file_path,
        "repository": repo_id,
        "branch": branch,
        "language": language,
        "contract_type": contract.contract_type,
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    # Add fields as JSON string
    if contract.fields:
        fields_json = ",".join(
            f"{f.name}:{f.type_annotation}" for f in contract.fields[:20]
        )
        meta["fields"] = fields_json

    collection.upsert(
        ids=[doc_id],
        documents=[content],
        metadatas=[meta],
    )

    return doc_id


def _store_entry_point(
    collection: chromadb.Collection,
    metadata: FileMetadata,
    repo_id: str,
    branch: str,
    timestamp: str,
) -> str:
    """Store an entry_point document."""
    entry_type = metadata.entry_point_type or "main"
    doc_id = f"{repo_id}:entry:{entry_type}:{metadata.file_path}"

    # Collect triggers from all functions
    triggers = []
    for func in metadata.functions:
        for trigger in func.triggers:
            if trigger.trigger_type == "http":
                triggers.append({
                    "type": "http",
                    "method": trigger.method,
                    "route": trigger.route,
                })
            elif trigger.trigger_type == "cli":
                triggers.append({
                    "type": "cli",
                    "command": trigger.command,
                    "args": trigger.args,
                })

    # Build searchable content
    content_parts = [
        f"{entry_type}: {metadata.file_path}",
        metadata.description,
    ]

    # Add function names for routes
    func_names = [f.name for f in metadata.functions if not f.name.startswith("_")]
    if func_names:
        content_parts.append(f"Functions: {', '.join(func_names[:10])}")

    # Add trigger info to searchable content
    if triggers:
        trigger_strs = []
        for t in triggers[:10]:
            if t["type"] == "http":
                trigger_strs.append(f"{t['method']} {t['route']}")
            elif t["type"] == "cli":
                trigger_strs.append(f"cli: {t.get('command', 'command')}")
        content_parts.append(f"Triggers: {', '.join(trigger_strs)}")

    content = "\n\n".join(content_parts)

    # Build metadata
    meta = {
        "type": "entry_point",
        "file_path": metadata.file_path,
        "repository": repo_id,
        "branch": branch,
        "language": metadata.language,
        "entry_type": entry_type,
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    # Add triggers as JSON
    if triggers:
        meta["triggers"] = json.dumps(triggers[:20])

    if metadata.file_hash:
        meta["file_hash"] = metadata.file_hash

    collection.upsert(
        ids=[doc_id],
        documents=[content],
        metadatas=[meta],
    )

    return doc_id


def build_dependencies(
    results: list[MetadataIngestionResult],
    collection: chromadb.Collection,
    repo_id: str,
    branch: str,
) -> int:
    """
    Build and store dependency documents from ingestion results.

    Creates dependency documents with forward and reverse import relationships.

    Args:
        results: List of MetadataIngestionResult from ingestion
        collection: ChromaDB collection
        repo_id: Repository identifier
        branch: Git branch name

    Returns:
        Number of dependency documents created
    """
    # Build import maps
    imports_map: dict[str, list[str]] = {}  # file -> [imported files]
    reverse_map: dict[str, list[str]] = {}  # file -> [files that import it]

    # Collect all file paths for resolution
    all_files = {r.file_path for r in results if r.metadata}

    for result in results:
        if not result.metadata:
            continue

        file_path = result.file_path
        imports_map[file_path] = []

        for imp in result.metadata.imports:
            if imp.is_external:
                continue

            # Try to resolve internal import to file path
            resolved = _resolve_import(imp.module, file_path, all_files)
            if resolved:
                imports_map[file_path].append(resolved)

                # Build reverse map
                if resolved not in reverse_map:
                    reverse_map[resolved] = []
                reverse_map[resolved].append(file_path)

    # Store dependency documents
    now = datetime.now(timezone.utc).isoformat()
    count = 0

    for file_path in imports_map:
        imports = imports_map.get(file_path, [])
        imported_by = reverse_map.get(file_path, [])

        if not imports and not imported_by:
            continue

        doc_id = f"{repo_id}:dep:{file_path}"

        content_parts = [file_path]
        if imports:
            content_parts.append(f"Imports: {', '.join(imports)}")
        if imported_by:
            content_parts.append(f"Imported by: {', '.join(imported_by)}")

        content = "\n\n".join(content_parts)

        # Calculate impact tier based on dependent count
        imported_by_count = len(imported_by)
        if imported_by_count > 5:
            impact_tier = "High"
        elif imported_by_count >= 2:
            impact_tier = "Medium"
        else:
            impact_tier = "Low"

        meta = {
            "type": "dependency",
            "file_path": file_path,
            "repository": repo_id,
            "branch": branch,
            "imports": ",".join(imports[:20]),
            "imported_by": ",".join(imported_by[:20]),
            "import_count": len(imports),
            "imported_by_count": imported_by_count,
            "impact_tier": impact_tier,
            "created_at": now,
            "updated_at": now,
        }

        collection.upsert(
            ids=[doc_id],
            documents=[content],
            metadatas=[meta],
        )
        count += 1

    logger.info(f"Built {count} dependency documents")
    return count


def link_test_files(
    results: list[MetadataIngestionResult],
    collection: chromadb.Collection,
    repo_id: str,
) -> int:
    """
    Link test files to their corresponding source files.

    Updates file_metadata documents with related_tests field.

    Matching strategies:
    1. Name pattern: test_foo.py ↔ foo.py, foo.test.ts ↔ foo.ts
    2. Import analysis: test files that import the source file

    Args:
        results: List of MetadataIngestionResult from ingestion
        collection: ChromaDB collection
        repo_id: Repository identifier

    Returns:
        Number of files updated with related_tests
    """
    # Separate test files from source files
    test_files = [r for r in results if r.metadata and r.metadata.is_test]
    source_files = [r for r in results if r.metadata and not r.metadata.is_test]

    if not test_files or not source_files:
        return 0

    # Build test file lookup by stem (without test_ prefix or _test suffix)
    test_by_target: dict[str, list[str]] = {}
    for test in test_files:
        test_path = Path(test.file_path)
        test_stem = test_path.stem

        # Extract target name from test file name
        target_stem = None
        if test_stem.startswith("test_"):
            target_stem = test_stem[5:]  # Remove "test_" prefix
        elif test_stem.endswith("_test"):
            target_stem = test_stem[:-5]  # Remove "_test" suffix
        elif test_stem.endswith(".test"):
            target_stem = test_stem[:-5]  # Remove ".test" suffix
        elif test_stem.endswith(".spec"):
            target_stem = test_stem[:-5]  # Remove ".spec" suffix

        if target_stem:
            if target_stem not in test_by_target:
                test_by_target[target_stem] = []
            test_by_target[target_stem].append(test.file_path)

    # Build import-based links
    import_links: dict[str, list[str]] = {}  # source -> [test files that import it]
    source_paths = {r.file_path for r in source_files}

    for test in test_files:
        if not test.metadata:
            continue
        for imp in test.metadata.imports:
            # Check if import resolves to a source file
            for source_path in source_paths:
                source_stem = Path(source_path).stem
                if source_stem in imp.module or imp.module.endswith(source_stem):
                    if source_path not in import_links:
                        import_links[source_path] = []
                    if test.file_path not in import_links[source_path]:
                        import_links[source_path].append(test.file_path)

    # Update file_metadata documents with related_tests
    updated = 0
    for source in source_files:
        source_stem = Path(source.file_path).stem
        related_tests = set()

        # Add name-pattern matches
        if source_stem in test_by_target:
            related_tests.update(test_by_target[source_stem])

        # Add import-based matches
        if source.file_path in import_links:
            related_tests.update(import_links[source.file_path])

        if related_tests:
            # Update the file_metadata document
            doc_id = f"{repo_id}:file:{source.file_path}"
            try:
                result = collection.get(ids=[doc_id], include=["documents", "metadatas"])
                if result["ids"]:
                    meta = result["metadatas"][0]
                    meta["related_tests"] = ",".join(sorted(related_tests)[:10])
                    collection.upsert(
                        ids=[doc_id],
                        documents=[result["documents"][0]],
                        metadatas=[meta],
                    )
                    updated += 1
            except Exception as e:
                logger.warning(f"Failed to update related_tests for {source.file_path}: {e}")

    logger.info(f"Linked {updated} source files to their tests")
    return updated


def _resolve_import(module: str, from_file: str, all_files: set[str]) -> Optional[str]:
    """
    Try to resolve an import module to a file path.

    Args:
        module: Import module string (e.g., ".models", "src.utils")
        from_file: Path of the importing file
        all_files: Set of all known file paths

    Returns:
        Resolved file path or None
    """
    if not module:
        return None

    from_path = Path(from_file)

    # Handle relative imports
    if module.startswith("."):
        # Count leading dots
        dots = len(module) - len(module.lstrip("."))
        relative_module = module.lstrip(".")

        # Go up directories based on dots
        base = from_path.parent
        for _ in range(dots - 1):
            base = base.parent

        # Try various file patterns
        candidates = [
            base / f"{relative_module.replace('.', '/')}.py",
            base / relative_module.replace(".", "/") / "__init__.py",
            base / f"{relative_module}.py",
        ]

        for candidate in candidates:
            candidate_str = str(candidate)
            if candidate_str in all_files:
                return candidate_str

    # Handle absolute imports (src.module style)
    else:
        module_path = module.replace(".", "/")
        candidates = [
            f"{module_path}.py",
            f"{module_path}/__init__.py",
        ]

        for candidate in candidates:
            if candidate in all_files:
                return candidate

    return None
