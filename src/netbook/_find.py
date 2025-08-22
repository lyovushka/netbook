import re
import typing_extensions as tp

import textual.app
import textual.binding
import textual.containers
import textual.reactive
import textual.widget
import textual.widgets
import textual.widgets.input

from netbook._cell import Cell, MarkdownCell

if tp.TYPE_CHECKING:
    from netbook import JupyterTextualApp


class Find(textual.containers.Horizontal, can_focus=True):
    hidden: textual.reactive.reactive[bool] = textual.reactive.reactive(True)
    match_index: textual.reactive.reactive[int | None] = textual.reactive.reactive(None, always_update=True)

    BINDINGS = [
        textual.binding.Binding("escape", "dismiss", "dismiss search widget"),
        textual.binding.Binding("enter", "find_next", "find_next", priority=True),
        textual.binding.Binding("shift+enter", "find_previous", "find previous"),
    ]

    def watch_hidden(self, hidden: bool) -> None:
        if hidden:
            self.add_class("hidden")
        else:
            self.remove_class("hidden")

    def watch_match_index(self, match_index: int | None) -> None:
        if not self.input.value:
            self.text.update("")
        elif len(self.matches) == 0:
            self.text.update("Not Found")
        elif match_index is None:
            self.text.update("")
        else:
            self.text.update(f" {match_index + 1} of {len(self.matches)} ")

    def __init__(self):
        super().__init__()
        self.app: JupyterTextualApp
        self.input = textual.widgets.Input(placeholder="Find", select_on_focus=False)
        self.match_case = textual.widgets.Checkbox(label="Match Case")
        self.whole_word = textual.widgets.Checkbox(label="Whole Word")
        self.regular_expression = textual.widgets.Checkbox(label="Regular Expression")
        self.text = textual.widgets.Static("", classes="match_text")
        self.matches: tp.List[tp.Tuple[Cell, textual.widgets.text_area.Selection]] = []

    def compose(self) -> textual.app.ComposeResult:
        def nf(widget: textual.widget.Widget) -> textual.widget.Widget:
            widget.can_focus = False
            return widget

        yield self.input
        yield nf(textual.widgets.Button("\uf106", action="find_previous"))
        yield nf(textual.widgets.Button("\uf107", action="find_next"))
        yield nf(self.match_case)
        yield nf(self.whole_word)
        yield nf(self.regular_expression)
        yield self.text
        yield nf(textual.widgets.Button("🗙", action="dismiss"))

    def select_match(self, index: int | None) -> None:
        self.match_index = index
        if self.match_index is not None:
            assert self.match_index < len(self.matches)
            cell, selection = self.matches[self.match_index]
            if isinstance(cell, MarkdownCell):
                cell.edit_mode = True
            cell.source.selection = selection

    def on_input_changed(self, event: textual.widgets.Input.Changed) -> None:
        self.update_search_results(select=True)

    def on_checkbox_changed(self, event: textual.widgets.Checkbox.Changed) -> None:
        self.update_search_results(select=True)

    def on_focus(self) -> None:
        self.input.focus()

    def reset_match(self) -> None:
        if self.match_index is not None:
            cell, selection = self.matches[self.match_index]
            if cell.source.selection == selection:
                with cell.source.prevent(textual.widgets.TextArea.SelectionChanged):
                    cell.source.selection = textual.widgets.text_area.Selection.cursor(cell.source.cursor_location)

    def update_search_results(self, select: bool) -> None:
        self.reset_match()
        self.matches = []
        self.match_index = None
        if not self.input.value:
            return

        pattern = self.input.value
        flags = re.IGNORECASE
        if not self.regular_expression.value:
            pattern = re.escape(pattern)
        if self.whole_word.value:
            pattern = f"\\b{pattern}\\b"
        if self.match_case.value:
            flags = re.NOFLAG

        try:
            pattern = re.compile(pattern, flags)
        except re.error:
            pass
        else:
            for cell in self.app.cells:
                self.matches += [
                    (
                        cell,
                        textual.widgets.text_area.Selection(
                            cell.source.document.get_location_from_index(match.start()),
                            cell.source.document.get_location_from_index(match.end()),
                        ),
                    )
                    for match in pattern.finditer(cell.source.text)
                ]

            self.select_match(0 if self.matches and select else None)

    def action_dismiss(self) -> None:
        focused_cell = self.app.cells[self.app.focused_cell_id]
        focused_cell.focus(False)
        self.hidden = True

    def action_show(self) -> None:
        focused_cell = self.app.cells[self.app.focused_cell_id]
        if focused_cell.has_class("input_focused") and focused_cell.source.selected_text:
            self.input.value = focused_cell.source.selected_text.replace("\n", "")
        elif selected_text := self.screen.get_selected_text():
            self.input.value = selected_text.replace("\n", "")
        self.input.selection = textual.widgets.input.Selection(0, len(self.input.value))
        self.hidden = False
        self.input.focus()
        self.update_search_results(select=True)

    def action_find_next(self) -> None:
        if len(self.matches) > 0:
            self.reset_match()
            self.select_match((self.match_index + 1) % len(self.matches) if self.match_index is not None else 0)

    def action_find_previous(self) -> None:
        if len(self.matches) > 0:
            self.reset_match()
            self.select_match(
                (self.match_index - 1) % len(self.matches) if self.match_index is not None else len(self.matches) - 1
            )
