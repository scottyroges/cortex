"""
Stats Panel Widget

Displays memory statistics: counts by type, repository, and language.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from src.browser.models import Stats


class StatsPanel(Widget):
    """
    Panel displaying Cortex memory statistics.

    Shows:
    - Total document count
    - Counts by type (notes, insights, commits, etc.)
    - Counts by repository
    """

    DEFAULT_CSS = """
    StatsPanel {
        width: 100%;
        height: auto;
        border: solid $primary;
        padding: 1;
    }

    StatsPanel .stats-title {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }

    StatsPanel .stats-section {
        margin-top: 1;
    }

    StatsPanel .stats-section-title {
        color: $text-muted;
        text-style: italic;
    }

    StatsPanel .stats-row {
        color: $text;
    }

    StatsPanel .stats-count {
        color: $success;
    }

    StatsPanel .stats-loading {
        color: $text-muted;
        text-style: italic;
    }

    StatsPanel .stats-error {
        color: $error;
    }
    """

    stats: reactive[Stats | None] = reactive(None)
    is_loading: reactive[bool] = reactive(True)
    error: reactive[str | None] = reactive(None)

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Vertical(
            Static("Memory Stats", classes="stats-title"),
            Static("Loading...", id="stats-content", classes="stats-loading"),
        )

    def watch_stats(self, stats: Stats | None) -> None:
        """React to stats changes."""
        if stats is not None:
            self._render_stats(stats)

    def watch_is_loading(self, is_loading: bool) -> None:
        """React to loading state changes."""
        content = self.query_one("#stats-content", Static)
        if is_loading:
            content.update("Loading...")
            content.add_class("stats-loading")
            content.remove_class("stats-error")

    def watch_error(self, error: str | None) -> None:
        """React to error state changes."""
        if error is not None:
            content = self.query_one("#stats-content", Static)
            content.update(f"Error: {error}")
            content.add_class("stats-error")
            content.remove_class("stats-loading")

    def _render_stats(self, stats: Stats) -> None:
        """Render the stats display."""
        content = self.query_one("#stats-content", Static)
        content.remove_class("stats-loading")
        content.remove_class("stats-error")

        lines = []

        # Total count
        lines.append(f"Total: [bold]{stats.total_documents:,}[/bold] documents")
        lines.append("")

        # By type
        if stats.by_type:
            lines.append("[dim]By Type:[/dim]")
            # Sort by count descending, but put semantic types first
            type_order = ["note", "insight", "commit", "initiative", "code", "web", "skeleton", "tech_stack", "focus"]
            sorted_types = sorted(
                stats.by_type.items(),
                key=lambda x: (type_order.index(x[0]) if x[0] in type_order else 100, -x[1])
            )
            for doc_type, count in sorted_types:
                # Use friendly names
                display_name = {
                    "note": "notes",
                    "insight": "insights",
                    "commit": "commits",
                    "initiative": "initiatives",
                    "code": "code chunks",
                    "web": "web pages",
                    "skeleton": "skeletons",
                    "tech_stack": "tech stacks",
                    "focus": "focus markers",
                }.get(doc_type, doc_type)
                lines.append(f"  {display_name}: [green]{count:,}[/green]")
            lines.append("")

        # By repository
        if stats.by_repository:
            lines.append("[dim]By Repository:[/dim]")
            # Sort by count descending
            sorted_repos = sorted(stats.by_repository.items(), key=lambda x: -x[1])
            for repo, count in sorted_repos[:5]:  # Show top 5
                lines.append(f"  {repo}: [green]{count:,}[/green]")
            if len(sorted_repos) > 5:
                remaining = sum(c for _, c in sorted_repos[5:])
                lines.append(f"  [dim]... +{len(sorted_repos) - 5} more ({remaining:,})[/dim]")

        content.update("\n".join(lines))

    def set_stats(self, stats: Stats) -> None:
        """Update the stats display."""
        self.is_loading = False
        self.error = None
        self.stats = stats

    def set_is_loading(self) -> None:
        """Set loading state."""
        self.is_loading = True
        self.error = None

    def set_error(self, message: str) -> None:
        """Set error state."""
        self.is_loading = False
        self.error = message
