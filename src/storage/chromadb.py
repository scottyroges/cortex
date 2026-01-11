"""
ChromaDB Client Management

Initialization and collection management for ChromaDB.
"""

import os
from typing import Any, Optional

import chromadb
from chromadb.config import Settings

from src.config import DB_PATH


def get_chroma_client(persist_dir: Optional[str] = None) -> chromadb.PersistentClient:
    """
    Initialize persistent ChromaDB client.

    Args:
        persist_dir: Directory for persistence (defaults to DB_PATH)

    Returns:
        ChromaDB PersistentClient instance
    """
    path = persist_dir or DB_PATH
    path = os.path.expanduser(path)
    # Ensure directory exists
    os.makedirs(path, exist_ok=True)
    return chromadb.PersistentClient(
        path=path,
        settings=Settings(anonymized_telemetry=False),
    )


def get_or_create_collection(
    client: chromadb.PersistentClient,
    name: str = "cortex_memory",
) -> chromadb.Collection:
    """
    Get or create the main collection with cosine similarity.

    Args:
        client: ChromaDB client
        name: Collection name

    Returns:
        ChromaDB Collection
    """
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def get_collection_stats(collection: chromadb.Collection) -> dict[str, Any]:
    """
    Get statistics about the collection.

    Args:
        collection: ChromaDB collection

    Returns:
        Dictionary with document_count and estimated_memory_mb
    """
    count = collection.count()
    return {
        "document_count": count,
        "estimated_memory_mb": count * 0.01,  # Rough estimate
    }
