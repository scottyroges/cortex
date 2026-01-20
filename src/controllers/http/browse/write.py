"""
Browse Write Endpoints

HTTP endpoints for updating and deleting documents.
"""

import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.configs import get_logger
from src.configs.services import get_collection, get_searcher

logger = get_logger("http.browse.write")

router = APIRouter()


class UpdateDocumentRequest(BaseModel):
    """Request model for updating a document."""

    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    files: Optional[list[str]] = None


# Editable fields per document type
EDITABLE_FIELDS = {
    "note": {"title", "content", "tags"},
    "insight": {"title", "content", "tags", "files"},
    "session_summary": {"content", "files"},
}


@router.put("/update")
def browse_update(
    id: str = Query(..., alias="id"),
    request: UpdateDocumentRequest = None,
) -> dict[str, Any]:
    """
    Update a document's editable fields.

    Args:
        id: Document ID
        request: Fields to update (title, content, tags, files)

    Only updates fields that are editable for the document's type.
    """
    doc_id = id
    logger.info(f"Browse update requested: doc_id={doc_id}")
    collection = get_collection()

    # Fetch existing document
    results = collection.get(
        ids=[doc_id],
        include=["documents", "metadatas", "embeddings"],
    )

    if not results["ids"]:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    current_content = results["documents"][0]
    current_metadata = results["metadatas"][0]
    current_embedding = (
        results["embeddings"][0]
        if results["embeddings"] is not None and len(results["embeddings"]) > 0
        else None
    )
    doc_type = current_metadata.get("type", "unknown")

    # Check if document type is editable
    if doc_type not in EDITABLE_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Document type '{doc_type}' is not editable",
        )

    allowed_fields = EDITABLE_FIELDS[doc_type]
    updated_fields = []

    # Update content if provided and allowed
    new_content = current_content
    if request.content is not None and "content" in allowed_fields:
        new_content = request.content
        updated_fields.append("content")

    # Update metadata fields
    new_metadata = current_metadata.copy()

    if request.title is not None and "title" in allowed_fields:
        new_metadata["title"] = request.title
        updated_fields.append("title")

    if request.tags is not None and "tags" in allowed_fields:
        new_metadata["tags"] = json.dumps(request.tags)
        updated_fields.append("tags")

    if request.files is not None and "files" in allowed_fields:
        new_metadata["files"] = json.dumps(request.files)
        updated_fields.append("files")

    if not updated_fields:
        raise HTTPException(
            status_code=400,
            detail="No valid fields provided for update",
        )

    # Upsert the updated document
    if current_embedding is not None:
        collection.upsert(
            ids=[doc_id],
            documents=[new_content],
            metadatas=[new_metadata],
            embeddings=[current_embedding],
        )
    else:
        collection.upsert(
            ids=[doc_id],
            documents=[new_content],
            metadatas=[new_metadata],
        )

    # Rebuild search index
    get_searcher().build_index()

    logger.info(f"Document {doc_id} updated: {updated_fields}")
    return {
        "success": True,
        "id": doc_id,
        "updated_fields": updated_fields,
    }


@router.delete("/delete")
def browse_delete(id: str = Query(..., alias="id")) -> dict[str, Any]:
    """
    Delete a document by ID.

    Args:
        id: Document ID to delete
    """
    doc_id = id
    logger.info(f"Browse delete requested: doc_id={doc_id}")
    collection = get_collection()

    # Verify document exists
    results = collection.get(ids=[doc_id], include=[])

    if not results["ids"]:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    # Delete the document
    collection.delete(ids=[doc_id])

    # Rebuild search index
    get_searcher().build_index()

    logger.info(f"Document {doc_id} deleted")
    return {
        "success": True,
        "id": doc_id,
    }


@router.delete("/delete-by-type")
def browse_delete_by_type(
    doc_type: str = Query(..., alias="type"),
    repository: Optional[str] = None,
) -> dict[str, Any]:
    """
    Delete all documents of a specific type.

    Args:
        type: Document type to delete (e.g., 'code', 'note')
        repository: Optional repository filter
    """
    logger.info(f"Browse delete by type requested: type={doc_type}, repository={repository}")
    collection = get_collection()

    # Build where filter
    where_filter: dict[str, Any] = {"type": doc_type}
    if repository:
        where_filter = {"$and": [{"type": doc_type}, {"repository": repository}]}

    # Get all matching documents
    results = collection.get(where=where_filter, include=[])

    if not results["ids"]:
        return {
            "success": True,
            "deleted_count": 0,
            "message": f"No documents found with type '{doc_type}'",
        }

    # Delete all matching documents
    collection.delete(ids=results["ids"])

    # Rebuild search index
    get_searcher().build_index()

    logger.info(f"Deleted {len(results['ids'])} documents of type '{doc_type}'")
    return {
        "success": True,
        "deleted_count": len(results["ids"]),
        "type": doc_type,
    }
