"""
Detail Screen

Full-screen document view for detailed reading.
"""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header

from src.browser.client import CortexClient, CortexClientError
from src.browser.terminal.widgets.detail_panel import DetailPanel


class DetailScreen(Screen):
    """
    Full-screen detail view.

    Used when more space is needed to read a document.
    Press Escape to return to the main screen.
    """

    DEFAULT_CSS = """
    DetailScreen {
        layout: vertical;
    }

    DetailScreen DetailPanel {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("escape", "go_back", "Back"),
    ]

    def __init__(self, client: CortexClient, doc_id: str):
        super().__init__()
        self.client = client
        self.doc_id = doc_id

    def compose(self) -> ComposeResult:
        """Create the layout."""
        yield Header()
        yield DetailPanel(id="detail")
        yield Footer()

    async def on_mount(self) -> None:
        """Load the document when screen is mounted."""
        detail_panel = self.query_one("#detail", DetailPanel)
        detail_panel.set_is_loading()

        try:
            doc = await self.client.get_document(self.doc_id)
            detail_panel.set_document(doc)
        except CortexClientError as e:
            detail_panel.set_error(str(e))

    def action_go_back(self) -> None:
        """Return to the main screen."""
        self.app.pop_screen()
