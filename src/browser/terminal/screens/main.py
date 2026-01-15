"""
Main Screen

The primary dashboard combining stats, list browser, and search.
"""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from src.browser.client import CortexClient, CortexClientError
from src.browser.terminal.widgets.detail_panel import DetailPanel
from src.browser.terminal.widgets.list_browser import DocumentSelected, ListBrowser
from src.browser.terminal.widgets.search_panel import (
    SearchPanel,
    SearchRequested,
    SearchResultSelected,
)
from src.browser.terminal.widgets.stats_panel import StatsPanel


class MainScreen(Screen):
    """
    Main dashboard screen.

    Layout:
    ┌──────────────────┬────────────────────────────────────────┐
    │  Stats Panel     │  List Browser                          │
    │                  │                                        │
    │                  ├────────────────────────────────────────┤
    │                  │  Detail Panel                          │
    │                  │                                        │
    ├──────────────────┴────────────────────────────────────────┤
    │  Search Panel                                             │
    └───────────────────────────────────────────────────────────┘
    """

    DEFAULT_CSS = """
    MainScreen {
        layout: grid;
        grid-size: 2 2;
        grid-columns: 1fr 3fr;
        grid-rows: 2fr 1fr;
    }

    #left-column {
        row-span: 2;
        height: 100%;
    }

    #right-top {
        height: 100%;
    }

    #right-bottom {
        height: 100%;
    }

    #bottom-row {
        column-span: 2;
        height: 100%;
    }

    .disconnected-banner {
        background: $error;
        color: $text;
        padding: 1;
        text-align: center;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("/", "focus_search", "Search"),
        ("escape", "clear_detail", "Clear"),
    ]

    def __init__(self, client: CortexClient):
        super().__init__()
        self.client = client

    def compose(self) -> ComposeResult:
        """Create the layout."""
        yield Header()
        with Container(id="left-column"):
            yield StatsPanel(id="stats")
        with Vertical(id="right-top"):
            yield ListBrowser(id="list")
        with Vertical(id="right-bottom"):
            yield DetailPanel(id="detail")
        with Container(id="bottom-row"):
            yield SearchPanel(id="search")
        yield Footer()

    async def on_mount(self) -> None:
        """Called when screen is mounted."""
        await self._load_data()

    async def _load_data(self) -> None:
        """Load stats and documents."""
        stats_panel = self.query_one("#stats", StatsPanel)
        list_browser = self.query_one("#list", ListBrowser)

        stats_panel.set_is_loading()
        list_browser.set_is_loading()

        try:
            # Load stats and documents in parallel
            stats = await self.client.get_stats()
            stats_panel.set_stats(stats)

            # Load documents (semantic types only, not code)
            docs = await self.client.list_documents(limit=200)
            # Filter to semantic types for the main list
            semantic_docs = [
                d for d in docs
                if d.doc_type in ("note", "insight", "commit", "initiative")
            ]
            list_browser.set_documents(semantic_docs)

            self.app.sub_title = "Connected"

        except CortexClientError as e:
            stats_panel.set_error(str(e))
            list_browser.set_error(str(e))
            self.app.sub_title = "Disconnected"

    async def on_document_selected(self, event: DocumentSelected) -> None:
        """Handle document selection from list."""
        await self._show_document(event.doc_id)

    async def on_search_result_selected(self, event: SearchResultSelected) -> None:
        """Handle search result selection."""
        await self._show_document(event.doc_id)

    async def on_search_requested(self, event: SearchRequested) -> None:
        """Handle search request."""
        search_panel = self.query_one("#search", SearchPanel)
        search_panel.set_searching()

        try:
            results = await self.client.search(event.query, limit=20, rerank=True)
            search_panel.set_results(results)
        except CortexClientError as e:
            search_panel.set_error(str(e))

    async def _show_document(self, doc_id: str) -> None:
        """Load and display a document in the detail panel."""
        detail_panel = self.query_one("#detail", DetailPanel)
        detail_panel.set_is_loading()

        try:
            doc = await self.client.get_document(doc_id)
            detail_panel.set_document(doc)
        except CortexClientError as e:
            detail_panel.set_error(str(e))

    def action_refresh(self) -> None:
        """Refresh all data."""
        self.run_worker(self._load_data())

    def action_focus_search(self) -> None:
        """Focus the search input."""
        search_panel = self.query_one("#search", SearchPanel)
        search_panel.focus_input()

    def action_clear_detail(self) -> None:
        """Clear the detail panel."""
        detail_panel = self.query_one("#detail", DetailPanel)
        detail_panel.clear()
