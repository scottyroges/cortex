"""
List Browser Widget

Displays a filterable, navigable list of documents.
"""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Select, Static

from src.browser.formatting import format_timestamp, truncate
from src.browser.models import DocumentSummary


class DocumentSelected(Message):
    """Message sent when a document is selected."""

    def __init__(self, doc_id: str) -> None:
        self.doc_id = doc_id
        super().__init__()


class DocumentListItem(ListItem):
    """A single document in the list."""

    def __init__(self, doc: DocumentSummary) -> None:
        super().__init__()
        self.doc = doc

    def compose(self) -> ComposeResult:
        """Create the list item content."""
        # Type indicator with color
        type_colors = {
            "note": "cyan",
            "insight": "yellow",
            "commit": "green",
            "initiative": "magenta",
            "code": "blue",
        }
        color = type_colors.get(self.doc.doc_type, "white")
        type_label = f"[{color}]{self.doc.doc_type[:4]}[/{color}]"

        # Title or ID
        title = self.doc.title or self.doc.id
        title = truncate(title, 40)

        # Timestamp
        timestamp = format_timestamp(self.doc.created_at) if self.doc.created_at else ""

        # Status indicator for insights
        status_indicator = ""
        if self.doc.doc_type == "insight":
            if self.doc.last_validation_result == "no_longer_valid":
                status_indicator = " [red]![/red]"
            elif self.doc.last_validation_result == "partially_valid":
                status_indicator = " [yellow]?[/yellow]"

        yield Static(
            f"{type_label} {title}{status_indicator} [dim]{timestamp}[/dim]"
        )


class ListBrowser(Widget):
    """
    Filterable list of documents.

    Features:
    - Filter by repository and type
    - Keyboard navigation (j/k or arrows)
    - Select document with Enter
    """

    DEFAULT_CSS = """
    ListBrowser {
        width: 100%;
        height: 100%;
        border: solid $primary;
    }

    ListBrowser .list-header {
        height: 3;
        padding: 0 1;
        background: $surface;
    }

    ListBrowser .list-title {
        text-style: bold;
        padding: 1 0;
    }

    ListBrowser .filter-row {
        height: auto;
    }

    ListBrowser Select {
        width: 20;
        margin-right: 1;
    }

    ListBrowser ListView {
        height: 1fr;
    }

    ListBrowser .list-empty {
        padding: 2;
        text-align: center;
        color: $text-muted;
    }

    ListBrowser .list-loading {
        padding: 2;
        text-align: center;
        color: $text-muted;
        text-style: italic;
    }
    """

    documents: reactive[list[DocumentSummary]] = reactive(list)
    is_loading: reactive[bool] = reactive(True)
    selected_repo: reactive[str] = reactive("all")
    selected_type: reactive[str] = reactive("all")

    # Available filter options (populated dynamically)
    repositories: reactive[list[str]] = reactive(list)

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        with Vertical():
            with Vertical(classes="list-header"):
                yield Label("Documents", classes="list-title")
                with Horizontal(classes="filter-row"):
                    yield Select(
                        [(("All Repos", "all"))],
                        value="all",
                        id="repo-filter",
                        prompt="Repository",
                    )
                    yield Select(
                        [
                            ("All Types", "all"),
                            ("Notes", "note"),
                            ("Insights", "insight"),
                            ("Commits", "commit"),
                            ("Initiatives", "initiative"),
                        ],
                        value="all",
                        id="type-filter",
                        prompt="Type",
                    )
            yield ListView(id="doc-list")

    def on_mount(self) -> None:
        """Called when widget is mounted."""
        self._show_loading()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle filter selection changes."""
        if event.select.id == "repo-filter":
            self.selected_repo = str(event.value)
        elif event.select.id == "type-filter":
            self.selected_type = str(event.value)
        # Trigger re-filter
        self._filter_documents()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle document selection."""
        if isinstance(event.item, DocumentListItem):
            self.post_message(DocumentSelected(event.item.doc.id))

    def watch_documents(self, documents: list[DocumentSummary]) -> None:
        """React to document list changes."""
        self._update_repo_filter(documents)
        self._filter_documents()

    def watch_repositories(self, repos: list[str]) -> None:
        """Update repository filter options."""
        repo_filter = self.query_one("#repo-filter", Select)
        options = [("All Repos", "all")]
        options.extend((repo, repo) for repo in sorted(repos))
        repo_filter.set_options(options)

    def _update_repo_filter(self, documents: list[DocumentSummary]) -> None:
        """Extract unique repositories from documents."""
        repos = sorted(set(doc.repository for doc in documents if doc.repository))
        self.repositories = repos

    def _filter_documents(self) -> None:
        """Apply filters and update the list view."""
        list_view = self.query_one("#doc-list", ListView)
        list_view.clear()

        filtered = self.documents

        # Apply repository filter
        if self.selected_repo != "all":
            filtered = [d for d in filtered if d.repository == self.selected_repo]

        # Apply type filter
        if self.selected_type != "all":
            filtered = [d for d in filtered if d.doc_type == self.selected_type]

        # Sort by created_at descending (most recent first)
        filtered = sorted(
            filtered,
            key=lambda d: d.created_at or "",
            reverse=True
        )

        if not filtered:
            list_view.mount(Static("No documents found", classes="list-empty"))
        else:
            for doc in filtered:
                list_view.mount(DocumentListItem(doc))

    def _show_loading(self) -> None:
        """Show loading state."""
        list_view = self.query_one("#doc-list", ListView)
        list_view.clear()
        list_view.mount(Static("Loading...", classes="list-loading"))

    def set_documents(self, documents: list[DocumentSummary]) -> None:
        """Update the document list."""
        self.is_loading = False
        self.documents = documents

    def set_is_loading(self) -> None:
        """Set loading state."""
        self.is_loading = True
        self._show_loading()

    def set_error(self, message: str) -> None:
        """Set error state."""
        self.is_loading = False
        list_view = self.query_one("#doc-list", ListView)
        list_view.clear()
        list_view.mount(Static(f"[red]Error: {message}[/red]", classes="list-empty"))
