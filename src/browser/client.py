"""
HTTP client for the Cortex daemon API.
"""

from typing import Optional

import httpx

from src.browser.models import (
    Document,
    DocumentSummary,
    SearchResponse,
    Stats,
)
from src.exceptions import (
    APIError,
    ClientError as CortexClientError,
    DaemonNotRunningError,
    DaemonTimeoutError,
)

# Re-export for backwards compatibility
__all__ = ["CortexClient", "CortexClientError", "DaemonNotRunningError", "DaemonTimeoutError", "APIError"]


class CortexClient:
    """
    Async HTTP client for the Cortex daemon browse API.

    Usage:
        client = CortexClient()
        stats = await client.get_stats()
    """

    def __init__(self, base_url: str | None = None):
        import os
        if base_url is None:
            base_url = os.environ.get("CORTEX_DAEMON_URL", "http://localhost:8000")
        self.base_url = base_url.rstrip("/")
        self._timeout = 10.0  # seconds

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
    ) -> dict:
        """Make an HTTP request to the daemon."""
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(method, url, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.ConnectError:
            raise DaemonNotRunningError(
                "Cannot connect to Cortex daemon. Run: cortex daemon start"
            )
        except httpx.TimeoutException:
            raise DaemonTimeoutError("Request to Cortex daemon timed out")
        except httpx.HTTPStatusError as e:
            raise APIError(f"API error: {e.response.status_code} - {e.response.text}")

    async def health_check(self) -> bool:
        """Check if the daemon is healthy."""
        try:
            data = await self._request("GET", "/health")
            return data.get("status") == "healthy"
        except CortexClientError:
            return False

    async def get_stats(self) -> Stats:
        """Get collection statistics."""
        data = await self._request("GET", "/browse/stats")
        return Stats.from_dict(data)

    async def list_documents(
        self,
        repository: Optional[str] = None,
        doc_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[DocumentSummary]:
        """
        List documents with optional filtering.

        Args:
            repository: Filter by repository name
            doc_type: Filter by document type (note, insight, commit, initiative, code)
            limit: Maximum results (default 50, max 500)
        """
        params = {"limit": limit}
        if repository:
            params["repository"] = repository
        if doc_type:
            params["type"] = doc_type

        data = await self._request("GET", "/browse/list", params=params)
        return [DocumentSummary.from_dict(item) for item in data]

    async def get_document(self, doc_id: str) -> Document:
        """Get a specific document by ID."""
        data = await self._request("GET", f"/browse/get/{doc_id}")
        return Document.from_dict(data)

    async def search(
        self,
        query: str,
        limit: int = 20,
        rerank: bool = True,
    ) -> SearchResponse:
        """
        Search memory with detailed scores.

        Args:
            query: Search query
            limit: Maximum results (default 20, max 100)
            rerank: Whether to apply reranking (default True)
        """
        params = {
            "q": query,
            "limit": limit,
            "rerank": str(rerank).lower(),
        }
        data = await self._request("GET", "/browse/search", params=params)
        return SearchResponse.from_dict(data)

    async def get_sample(self, limit: int = 10) -> list[DocumentSummary]:
        """Get a sample of documents."""
        params = {"limit": limit}
        data = await self._request("GET", "/browse/sample", params=params)
        # Sample returns content_preview, convert to DocumentSummary format
        return [
            DocumentSummary(
                id=item.get("id", ""),
                doc_type=item.get("metadata", {}).get("type", "unknown"),
                repository=item.get("metadata", {}).get("repository", "unknown"),
                title=item.get("metadata", {}).get("title"),
                created_at=item.get("metadata", {}).get("created_at"),
            )
            for item in data
        ]
