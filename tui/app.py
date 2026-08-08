"""Tropelex TUI — terminal dashboard for browsing and capturing decisions.

Reaches anyone who lives in a terminal/tmux rather than an editor, using the
same REST API the dashboard, VSCode extension, and Emacs package all share.
Requires the Tropelex server running (default http://localhost:8766).
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, ListItem, ListView, Select, Static

import client


class AddDecisionScreen(ModalScreen[tuple[str, str, str] | None]):
    """Modal for capturing a new decision.

    safety_category has no pre-selected default — add_decision on the
    server rejects a missing/omitted category rather than silently
    assigning one (see core/triggers/tag_gate.py). Submitting without
    picking one just shows a hint instead of dismissing.
    """

    CSS = """
    AddDecisionScreen {
        align: center middle;
    }
    #dialog {
        width: 70;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #dialog Input, #dialog Select {
        margin-bottom: 1;
    }
    #dialog Label.hint {
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Capture a decision")
            yield Input(placeholder="Decision — what did you decide?", id="decision-input")
            yield Input(placeholder="Context — why? (optional)", id="context-input")
            yield Select(
                [(c, c) for c in client.SAFETY_CATEGORIES],
                prompt="Safety category — required",
                id="category-select",
            )
            yield Label("Enter to submit · Escape to cancel", classes="hint", id="hint-label")

    def on_mount(self) -> None:
        self.query_one("#decision-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        decision = self.query_one("#decision-input", Input).value.strip()
        context = self.query_one("#context-input", Input).value.strip()
        category = self.query_one("#category-select", Select).value
        if not decision:
            return
        if category is Select.BLANK:
            self.query_one("#hint-label", Label).update(
                "Pick a safety category first — Escape to cancel"
            )
            return
        self.dismiss((decision, context, category))

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class TropelexTUI(App):
    """Terminal dashboard for Tropelex — browse projects, decisions, capture new ones."""

    CSS = """
    #main { height: 1fr; }
    #sidebar { width: 30; border-right: solid $accent; padding: 0 1; }
    #content { width: 1fr; }
    #status { height: 1; background: $panel; padding: 0 1; }
    .section-title { text-style: bold; color: $accent; margin-top: 1; }
    """

    BINDINGS = [
        Binding("a", "add_decision", "Add decision"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.current_project: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Label("Projects", classes="section-title")
                yield ListView(id="project-list")
            with Vertical(id="content"):
                yield DataTable(id="decisions-table")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#decisions-table", DataTable)
        table.add_columns("When", "Decision", "Confidence")
        table.cursor_type = "row"
        self.run_worker(self.load_projects())

    async def load_projects(self) -> None:
        list_view = self.query_one("#project-list", ListView)
        await list_view.clear()
        self.set_status("Loading projects...")
        try:
            projects = await client.list_projects()
        except client.TropelexError as exc:
            self.set_status(f"Error: {exc}")
            return
        names: list[str] = []
        for p in projects:
            name = p.get("name", str(p)) if isinstance(p, dict) else str(p)
            names.append(name)
            await list_view.append(ListItem(Label(name), name=name))
        if names:
            await self.select_project(names[0])
        else:
            self.set_status("No projects yet.")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "project-list" and event.item is not None:
            name = event.item.name
            if name:
                self.run_worker(self.select_project(name))

    async def select_project(self, project: str) -> None:
        self.current_project = project
        self.set_status(f"Loading {project}...")
        try:
            memory = await client.get_project_memory(project)
        except client.TropelexError as exc:
            self.set_status(f"Error: {exc}")
            return

        table = self.query_one("#decisions-table", DataTable)
        table.clear()
        decisions = memory.get("decisions", [])
        decisions_sorted = sorted(decisions, key=lambda d: d.get("timestamp") or "", reverse=True)
        for d in decisions_sorted[:200]:
            ts = (d.get("timestamp") or "")[:16].replace("T", " ")
            text = (d.get("decision") or "")[:70]
            conf = d.get("confidence")
            tier = conf.get("tier", "-") if isinstance(conf, dict) else "-"
            table.add_row(ts, text, tier)

        try:
            contradictions = await client.get_contradictions(project)
            c_count = contradictions.get("unresolved_count", 0)
        except client.TropelexError:
            c_count = "?"

        self.set_status(
            f"{project}  ·  {len(decisions)} decisions  ·  {c_count} unresolved contradictions"
            f"  ·  [a] add  [r] refresh  [q] quit"
        )

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def action_refresh(self) -> None:
        if self.current_project:
            self.run_worker(self.select_project(self.current_project))
        else:
            self.run_worker(self.load_projects())

    def action_add_decision(self) -> None:
        if not self.current_project:
            self.set_status("Select a project first")
            return

        def handle_result(result: tuple[str, str, str] | None) -> None:
            if result:
                self.run_worker(self._submit_decision(result[0], result[1], result[2]))

        self.push_screen(AddDecisionScreen(), handle_result)

    async def _submit_decision(self, decision: str, context: str, safety_category: str) -> None:
        assert self.current_project
        try:
            await client.add_decision(self.current_project, decision, context, safety_category)
        except client.TropelexError as exc:
            self.set_status(f"Error: {exc}")
            return
        await self.select_project(self.current_project)
        self.set_status(f"Captured: {decision[:60]}")


def main() -> None:
    TropelexTUI().run()


if __name__ == "__main__":
    main()
