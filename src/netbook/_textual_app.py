import asyncio
import collections
import dataclasses
import enum
import importlib
import pathlib
import sys
import time
import typing_extensions as tp

import jupyter_client

import nbformat

import rich.console

import textual.app
import textual.containers
import textual.widgets
import textual.widgets.text_area
import textual.binding
import textual._border

import tree_sitter

from netbook._cell import Cell, CodeCell, RawCell, MarkdownCell
from netbook._text_area import CellTextArea
from netbook._find import Find

# Monkeypatch "double" for a custom border. Not great, but will do for now.
textual._border.BORDER_CHARS["double"] = (
    ("▄", " ", " "),
    ("█", " ", " "),
    ("▀", " ", " "),
)


class JupyterTextualApp(textual.app.App, inherit_bindings=False):
    CSS_PATH = "netbook.css"

    COMMAND_PALETTE_BINDING = "ctrl+shift+f,ctrl+shift+p,p"

    AUTO_FOCUS = "CellTextArea"

    REPEAT_KEY_PRESS_TIME = 0.8

    CMDTRL = "super" if sys.platform == "darwin" else "ctrl"

    DUMMY_BINDING = "__dummy"

    show_line_numbers: textual.reactive.reactive[bool] = textual.reactive.reactive(True, init=False)

    def _watch_show_line_numbers(self, show_line_numbers: bool) -> None:
        for cell in self.cells:
            cell.source.show_line_numbers = show_line_numbers

    unsaved: textual.reactive.reactive[bool] = textual.reactive.reactive(False, init=False, repaint=False)

    def _watch_unsaved(self, unsaved: bool) -> None:
        self.unsaved_marker.update("•" if unsaved else "")

    @dataclasses.dataclass
    class CellDeletion:
        position: int
        nbformats: list[str]

    def __init__(
        self,
        kernel_manager: jupyter_client.KernelManager,
        kernel_client: jupyter_client.AsyncKernelClient,
        nbfile: str,
        nb: nbformat.NotebookNode | None,
        image_class: type,
    ) -> None:
        super().__init__()
        self.kernel_manager = kernel_manager
        self.kernel_client = kernel_client
        self.nbfile = nbfile
        self.nb = nb or nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell()])
        self.start_cell_id = self.focused_cell_id = 0

        self.copied_cells_nbformat: tp.List[nbformat.NotebookNode] = []
        self.cell_deletion_stack: collections.deque[self.CellDeletion] = collections.deque()

        self.kernel_access_queue: set[asyncio.Future] = set()

        self.scroll = textual.containers.Container(classes="mainscroll")
        self.add_cell_button = textual.widgets.Button(
            "Click to add a cell.", classes="click_to_add_cell", action="app.insert_cell_at_end"
        )

        self.cell_type_selector = textual.widgets.Select(
            [(x, x.lower()) for x in ["Code", "Markdown", "Raw"]], allow_blank=False, value=self.nb.cells[0].cell_type
        )
        self.kernel_state = textual.widgets.Static("○")
        self.unsaved_marker = textual.widgets.Static("")

        self.find = Find()

        self.repeat_key = None
        self.repeat_key_count = 0
        self.last_key_press_time = time.monotonic()

        self.image_class = image_class

        self._load_language()
        self.call_after_refresh(lambda: self.queue_for_kernel(self._initialize_kernel))

    @property
    def cells(self) -> list[Cell]:
        return self.scroll.children[:-1]

    def _load_language(self) -> None:
        self.tree_sitter_language, self.language_highlights_query = None, ""
        language = self.kernel_manager.kernel_spec.language
        ll = language.lower()
        if ll not in textual.widgets.text_area.BUILTIN_LANGUAGES:
            try:
                m = importlib.import_module(f"tree_sitter_{ll}")
                tree_sitter_language = tree_sitter.Language(m.language(), name=language)
                if not hasattr(m, "HIGHLIGHTS_QUERY"):
                    # Last ditch attempt to get the query. Works e.g. for julia
                    m._get_query("HIGHLIGHTS_QUERY", "highlights.scm")
                language_highlights_query = m.HIGHLIGHTS_QUERY
            except (ModuleNotFoundError, AttributeError, OSError):
                self.notify(
                    f"Syntax highlighting is not available for {language}. Try installing the package `tree_sitter_{ll}`"
                )
            else:
                # Only set those if everything was successful
                self.tree_sitter_language = tree_sitter_language
                self.language_highlights_query = language_highlights_query

    async def _initialize_kernel(self) -> None:
        if self.kernel_manager.kernel_spec.language == "python":
            # Enrich the output with Rich
            with open(pathlib.Path(__file__).parent.joinpath("_ipykernel_init.py")) as init_file:
                await self.kernel_client.execute_interactive(
                    init_file.read(), silent=True, output_hook=lambda msg: None
                )
        self.notify("kernel ready")

    def _kernel_task_done_callback(self, task: asyncio.Task) -> None:
        if task not in self.kernel_access_queue:
            # self.kernel_access_queue was reset. Return here so we don't mess up with the new tasks
            return
        self.kernel_access_queue.remove(task)
        if len(self.kernel_access_queue) == 0:
            self.kernel_state.update("○")
        if not task.cancelled():
            exception = task.exception()
            if exception:
                self.cancel_kernel_tasks()
            if isinstance(exception, TimeoutError):
                self.notify("kernel appears to have died, restarting")
                self.kernel_manager.restart_kernel()
                assert len(self.kernel_access_queue) == 0
                self.queue_for_kernel(self._initialize_kernel)

    def queue_for_kernel(
        self,
        task: tp.Callable[..., tp.Coroutine],
        *args,
        **kwargs,
    ) -> asyncio.Task:
        tasks_to_await = list(self.kernel_access_queue)  # Copying the state at this point

        async def _task():
            try:
                await asyncio.gather(*tasks_to_await)
            except Exception as e:
                raise asyncio.CancelledError() from e
            else:
                self.kernel_state.update("●")
                await task(*args, **kwargs)

        wrapped_task = asyncio.create_task(_task())
        wrapped_task.add_done_callback(self._kernel_task_done_callback)
        self.kernel_access_queue.add(wrapped_task)
        return wrapped_task

    def cancel_kernel_tasks(self) -> None:
        for task in self.kernel_access_queue:
            task.cancel()
        self.kernel_access_queue = set()
        self.kernel_state.update("○")

    def _get_selected_cells_range(self) -> tp.Tuple[int, int]:
        return min(self.start_cell_id, self.focused_cell_id), max(self.start_cell_id, self.focused_cell_id)

    class Range(enum.StrEnum):
        all = "all"
        selection = "selection"
        above = "above"
        below = "below"

    def _get_range_cells(self, range: Range) -> tp.Iterable[Cell]:
        match range:
            case self.Range.all:
                return self.cells
            case self.Range.selection:
                start_id, end_id = self._get_selected_cells_range()
                return self.cells[start_id : end_id + 1]
            case self.Range.above:
                return self.cells[: self.focused_cell_id]
            case self.Range.below:
                return self.cells[self.focused_cell_id :]
            case _:
                assert False, f"Unsupported {range=}"

    def _adjust_cell_classes(self, fucused_cell: Cell, input_focused: bool, extend_selection: bool) -> None:
        above_focused = True
        for i, cell_ in enumerate(self.cells):
            # Since add_classes and remove_classes are expensive, we want to do it only once per cell.
            # So we try to figure out the classes in one pass.
            # The logic is a bit convoluted

            if cell_ is fucused_cell:
                self.focused_cell_id = i
                above_focused = False
                remove_classes = ["below_focused", "above_focused"]
                add_classes = ["focused"]
                if input_focused:
                    add_classes.append("input_focused")
                else:
                    remove_classes.append("input_focused")
                if not extend_selection or self.start_cell_id == self.focused_cell_id:
                    remove_classes.append("multiselect")
                else:
                    add_classes.append("multiselect")

            elif above_focused:
                remove_classes = ["focused", "input_focused", "below_focused"]
                add_classes = ["above_focused"]
                if not extend_selection or i < self.start_cell_id:
                    remove_classes.append("multiselect")
                else:
                    add_classes.append("multiselect")

            else:
                remove_classes = ["focused", "input_focused", "above_focused"]
                add_classes = ["below_focused"]
                if not extend_selection or i > self.start_cell_id:
                    remove_classes.append("multiselect")
                else:
                    add_classes.append("multiselect")

            if cell_.has_class(*add_classes):
                # add_class will not update so need to update on remove_class
                cell_.remove_class(*remove_classes)
            else:
                cell_.remove_class(*remove_classes, update=False)
                cell_.add_class(*add_classes)

        if not extend_selection:
            self.start_cell_id = self.focused_cell_id

        with self.cell_type_selector.prevent(textual.widgets.Select.Changed):
            self.cell_type_selector.value = fucused_cell.cell_type()

    async def _on_select_changed(self, message: textual.widgets.Select.Changed) -> None:
        if self.cells[self.focused_cell_id].cell_type() != message.value:
            # This function gets called at the beginning.
            # The above conditions is meant to ensure we don't call the action at the beginning.
            await self.action_change_cell_to(message.value)

    def _on_cell_text_area_cursor_out_bottom(self, message: CellTextArea.CursorOutBottom) -> None:
        if self.focused_cell_id + 1 < len(self.cells) and self.cells[self.focused_cell_id].source is message.text_area:
            next_cell = self.cells[self.focused_cell_id + 1]
            next_cell.source.move_cursor(next_cell.source.document.start)
            with next_cell.prevent(Cell.Focused):
                next_cell.action_edit_mode()
            self._focus_cell(next_cell, input_focused=True, scroll_visible=False)
            self._scroll_to_cursor(next_cell.source)

    def _on_cell_text_area_cursor_out_top(self, message: CellTextArea.CursorOutTop) -> None:
        if self.focused_cell_id > 0 and self.cells[self.focused_cell_id].source is message.text_area:
            previous_cell = self.cells[self.focused_cell_id - 1]
            previous_cell.source.move_cursor(previous_cell.source.document.end)
            with previous_cell.prevent(Cell.Focused):
                previous_cell.action_edit_mode()
            self._focus_cell(previous_cell, input_focused=True, scroll_visible=False)
            self._scroll_to_cursor(previous_cell.source)

    def _on_key(self, event: textual.events.Key) -> None:
        now = time.monotonic()
        if self.repeat_key == event.key and now - self.last_key_press_time < self.REPEAT_KEY_PRESS_TIME:
            self.repeat_key_count += 1
        else:
            self.repeat_key = event.key
            self.repeat_key_count = 1
        self.last_key_press_time = now

    def _on_app_focus(self, event: textual.events.AppFocus) -> None:
        focused_cell = self.cells[self.focused_cell_id]
        if focused_cell.has_class("input_focused"):
            focused_cell.source.focus(False)
        else:
            focused_cell.focus(False)

    def _on_cell_focused(self, event: Cell.Focused) -> None:
        self._adjust_cell_classes(event.cell, event.input, False)

    def _on_descendant_focus(self, event: textual.events.DescendantFocus) -> None:
        if not self.scroll.has_focus_within:
            self.cells[self.focused_cell_id].remove_class("input_focused")

    def _on_text_area_selection_changed(self, event: textual.widgets.TextArea.SelectionChanged) -> None:
        self._scroll_to_cursor(event.text_area)

    def _on_text_area_changed(self, event: textual.widgets.TextArea.Changed) -> None:
        self.unsaved = True
        if not self.find.hidden:
            self.find.update_search_results(False)

    def _on_code_cell_new_output(self, message: CodeCell.NewOutput) -> None:
        self.unsaved = True

    def _scroll_to_cursor(self, text_area: textual.widgets.TextArea):
        # scroll self.scroll so that the cursor is visible
        region = textual.geometry.Region(text_area._cursor_offset[0], text_area._cursor_offset[1], width=3, height=1)
        widget = text_area
        while widget is not self.scroll:
            region = region.translate(widget.virtual_region.offset).translate(widget.styles.gutter.top_left)
            widget = widget.parent
        self.scroll.scroll_to_region(region, animate=False, immediate=True)

    def _focus_cell(
        self, cell: Cell, *, input_focused: bool = False, scroll_visible: bool = True, extend_selection: bool = False
    ) -> None:
        self._adjust_cell_classes(cell, input_focused, extend_selection)
        to_focus = cell.source if input_focused else cell
        with cell.prevent(Cell.Focused):
            self.set_focus(to_focus, scroll_visible=False)
        # scroll_visible is quite finicky. It seems like Widget.scroll_visible works best.
        if scroll_visible and not self.screen.can_view_entire(cell):
            cell.scroll_visible(immediate=True, force=True)

    @tp.override
    def exit(
        self,
        result: textual.app.ReturnType | None = None,
        return_code: int = 0,
        message: rich.console.RenderableType | None = None,
    ) -> None:
        self.kernel_client.shutdown()
        super().exit(result, return_code, message)

    def compose(self) -> textual.app.ComposeResult:
        def nf(widget: textual.widget.Widget) -> textual.widget.Widget:
            widget.can_focus = False
            return widget

        with textual.containers.Horizontal(classes="toolbar"):
            yield textual.widgets.Static(" ")
            yield nf(textual.widgets.Button("\uf0c7", action="app.save", tooltip="save"))
            yield textual.widgets.Static(" ")
            yield nf(textual.widgets.Button("\uf067", action="app.insert_cell_below", tooltip="insert cell below"))
            yield textual.widgets.Static(" ")
            yield nf(textual.widgets.Button("\uf0c4", action="app.cut_selected_cells", tooltip="cut selected cells"))
            yield nf(textual.widgets.Button("\uf0c5", action="app.copy_selected_cells", tooltip="copy selected cells"))
            yield nf(textual.widgets.Button("\uf0ea", action="app.paste_cells_below", tooltip="paste cells below"))
            yield textual.widgets.Static(" ")
            yield nf(
                textual.widgets.Button(
                    "\uf063", action="app.move_selected_cells_down", tooltip="move selected cells down"
                )
            )
            yield nf(
                textual.widgets.Button("\uf062", action="app.move_selected_cells_up", tooltip="move selected cells up")
            )
            yield textual.widgets.Static(" ")
            yield nf(
                textual.widgets.Button(
                    "\uf04b Run", action="app.run_cell_and_select_below", tooltip="run cell and select below"
                )
            )
            yield nf(textual.widgets.Button("\uf04d", action="app.interrupt_kernel", tooltip="interrupt the kernel"))
            yield nf(textual.widgets.Button("\uf01e", action="app.restart_kernel", tooltip="restart the kernel"))
            yield nf(
                textual.widgets.Button(
                    "\uf04e",
                    action="app.restart_and_run_all",
                    tooltip="restart the kernel, then re-run the whole notebook",
                )
            )
            yield textual.widgets.Static(" ")
            yield self.cell_type_selector
            yield textual.widgets.Static(" ")
            yield nf(textual.widgets.Button("\uf11c", action="app.command_palette"))
            yield textual.widgets.Static(" ", classes="spacer")
            with textual.containers.Horizontal(classes="title"):
                yield textual.widgets.Static(f"{pathlib.Path(self.nbfile).stem}")
                yield self.unsaved_marker
                yield textual.widgets.Static(f" | {self.kernel_manager.kernel_spec.display_name} ")
                yield self.kernel_state
        with self.scroll:
            for i, cell in enumerate(self.nb.cells):
                yield Cell.from_nbformat(cell).add_class("focused" if i == 0 else "below_focused")
            yield nf(self.add_cell_button)
        yield self.find

    BINDINGS = [
        textual.binding.Binding("ctrl+q", "try_quit", "quit the application"),
        textual.binding.Binding(f"{CMDTRL}+f", "find", "find", priority=True),
        textual.binding.Binding("f,/", "find", "find"),
        textual.binding.Binding(f"{CMDTRL}+shift+f,{CMDTRL}+shift+p,p", "command_palette", "open the command palette"),
        textual.binding.Binding("shift+enter", "run_cell_and_select_below", "run cell and select below"),
        textual.binding.Binding(f"ctrl+enter,{CMDTRL}+enter", "run_cells('selection')", "run cell"),
        textual.binding.Binding("alt+enter", "run_cell_and_insert_below", "run cell and insert below"),
        textual.binding.Binding("y", "change_cell_to('code')", "change cell to code"),
        textual.binding.Binding("m", "change_cell_to('markdown')", "change cell to markdown"),
        textual.binding.Binding("r", "change_cell_to('raw')", "change cell to raw"),
        textual.binding.Binding("k,up", "select_cell_above", "select cell above"),
        textual.binding.Binding("j,down", "select_cell_below", "select cell below"),
        textual.binding.Binding("K,shift+up", "extend_selection_above", "extend selection above"),
        textual.binding.Binding("J,shift+down", "extend_selection_below", "extend selection below"),
        textual.binding.Binding(f"{CMDTRL}+a", "select_all_cells", "select all cells"),
        textual.binding.Binding("ctrl+shift+up", "move_selected_cells_up", "move selected cells up"),
        textual.binding.Binding("ctrl+shift+down", "move_selected_cells_down", "move selected cells down"),
        textual.binding.Binding("a", "insert_cell_above", "insert cell above"),
        textual.binding.Binding("b", "insert_cell_below", "insert cell below"),
        textual.binding.Binding("x", "cut_selected_cells", "cut selected cells"),
        textual.binding.Binding("c", "copy_selected_cells", "copy selected cells"),
        textual.binding.Binding("V", "paste_cells_above", "paste cells above"),
        textual.binding.Binding("v", "paste_cells_below", "paste cells below"),
        textual.binding.Binding("z", "undo_cell_deletion", "undo cell deletion"),
        textual.binding.Binding("d", "try_delete_selected_cells", "delete selected cells", key_display="d,d"),
        textual.binding.Binding("M", "merge_selected_cells", "merge selected cells, or single cell below"),
        textual.binding.Binding("l", "toggle_line_numbers", "toggle line numbers"),
        textual.binding.Binding("L", "set_line_numbers_in_all_cells(None)", "toggle line numbers in all cells"),
        textual.binding.Binding("o", "toggle_output('selection')", "toggle output of selected cells"),
        textual.binding.Binding(
            "O", "toggle_output_scrolling('selection')", "toggle output scrolling of selected cells"
        ),
        textual.binding.Binding(f"s,{CMDTRL}+s", "save_notebook", "save notebook"),
        textual.binding.Binding("h", "toggle_help", "show keyboard shortcuts"),
        textual.binding.Binding("i", "try_interrupt_kernel", "interrupt the kernel", key_display="i,i"),
        textual.binding.Binding("0", "try_restart_kernel", "restart the kernel", key_display="0,0"),
        textual.binding.Binding("ctrl+shift+minus", "split_cell_at_cursor", "split cell at cursor(s)"),
        textual.binding.Binding(
            DUMMY_BINDING, "clear_cell_output('all')", "clear all cells output", show=False, system=True
        ),
        textual.binding.Binding(
            DUMMY_BINDING, "clear_cell_output('selection')", "clear cell output", show=False, system=True
        ),
        textual.binding.Binding(
            DUMMY_BINDING, "set_line_numbers_in_all_cells(False)", "hide all line numbers", show=False, system=True
        ),
        textual.binding.Binding(DUMMY_BINDING, "quit", "quit the application without saving", show=False, system=True),
        textual.binding.Binding(
            DUMMY_BINDING, "restart_and_run_all", "restart kernel and run all cells", show=False, system=True
        ),
        textual.binding.Binding(DUMMY_BINDING, "run_cells('all')", "run all cells", show=False, system=True),
        textual.binding.Binding(DUMMY_BINDING, "run_cells('above')", "run all cells above"),
        textual.binding.Binding(DUMMY_BINDING, "run_cells('below')", "run all cells below"),
        textual.binding.Binding(
            DUMMY_BINDING, "set_line_numbers_in_all_cells(True)", "show all line numbers", show=False, system=True
        ),
        textual.binding.Binding(
            DUMMY_BINDING, "toggle_output('all')", "toggle all cells output collapsed", show=False, system=True
        ),
        textual.binding.Binding(
            DUMMY_BINDING, "toggle_output_scrolling('all')", "toggle all cells output scrolled", show=False, system=True
        ),
    ]

    @tp.override
    def get_key_display(self, binding: textual.binding.Binding) -> str:
        if binding.key == self.DUMMY_BINDING:
            return ""
        return super().get_key_display(binding)

    def get_system_commands(self, screen: textual.screen.Screen) -> tp.Iterable[textual.app.SystemCommand]:
        desc_to_bindings = {}
        for key, binding in self._bindings:
            desc_to_bindings.setdefault(binding.description, []).append(binding)

        for description, bindings in sorted(desc_to_bindings.items()):
            # Python footgun 101: `bindings` is a loop variable.
            async def callback(bindings=bindings):
                await self.run_action(bindings[0].action)

            # dict.fromkeys makes them unique and preserves the order
            help = " ".join(dict.fromkeys(self.get_key_display(binding) for binding in bindings))
            yield textual.app.SystemCommand(description, help, callback)

    def check_action(self, action: str, parameters) -> bool | None:
        if action == "split_cell_at_cursor":
            return self.cells[self.focused_cell_id].source.has_focus_within
        return True

    async def action_clear_cell_output(self, range: Range) -> None:
        for cell in self._get_range_cells(range):
            if isinstance(cell, CodeCell):
                await cell.clear_outputs()
        self.unsaved = True

    async def action_try_quit(self):
        if self.repeat_key_count < 2 and self.unsaved:
            self.notify("To quit without saving press ctrl+q twice", title="Unsaved changes", severity="warning")
        else:
            await self.action_quit()

    def action_find(self) -> None:
        self.find.action_show()

    async def action_run_cell_and_select_below(self) -> None:
        start_id, end_id = self._get_selected_cells_range()
        for cell in self.cells[start_id : end_id + 1]:
            cell.execute()
        if end_id + 1 == len(self.cells):
            # Last cell; add a new one.
            below_cell = CodeCell(classes="below_focused")
            await self.scroll.mount(below_cell, after=end_id)
            self._focus_cell(below_cell, input_focused=True)
        else:
            # Not focusing the source here
            self._focus_cell(self.cells[end_id + 1], input_focused=False)
        self.unsaved = True

    def action_run_cells(self, range: Range) -> None:
        cells = self._get_range_cells(range)
        assert len(cells) > 0
        for cell in cells:
            cell.execute()
        self._focus_cell(cells[-1])
        self.unsaved = True

    async def action_run_cell_and_insert_below(self):
        start_id, end_id = self._get_selected_cells_range()
        for cell in self.cells[start_id : end_id + 1]:
            cell.execute()
        new_cell = CodeCell(classes="below_focused")
        await self.scroll.mount(new_cell, after=end_id)
        self._focus_cell(new_cell, input_focused=True)
        self.unsaved = True

    async def action_change_cell_to(self, cell_type: str) -> None:
        start_id, end_id = self._get_selected_cells_range()
        new_class = {"code": CodeCell, "raw": RawCell, "markdown": MarkdownCell}[cell_type]
        cell_to_focus = self.cells[end_id]
        self.set_focus(None)
        with self.batch_update():
            for i in range(start_id, end_id + 1):
                if not isinstance(self.cells[i], new_class):
                    new_cell = new_class(self.cells[i].source.text, classes=" ".join(self.cells[i].classes))
                    await self.scroll.mount(new_cell, after=i)
                    await self.cells[i].remove()
                    cell_to_focus = new_cell
                    self.unsaved = True
        self._focus_cell(cell_to_focus)

    def action_select_cell_above(self) -> None:
        if self.focused_cell_id > 0:
            self._focus_cell(self.cells[self.focused_cell_id - 1])

    def action_select_cell_below(self) -> None:
        if self.focused_cell_id + 1 < len(self.cells):
            self._focus_cell(self.cells[self.focused_cell_id + 1])

    def action_extend_selection_above(self) -> None:
        if self.focused_cell_id > 0:
            self._focus_cell(self.cells[self.focused_cell_id - 1], extend_selection=True)

    def action_extend_selection_below(self) -> None:
        if self.focused_cell_id + 1 < len(self.cells):
            self._focus_cell(self.cells[self.focused_cell_id + 1], extend_selection=True)

    def action_select_all_cells(self) -> None:
        self.start_cell_id = 0
        self._focus_cell(self.cells[-1], extend_selection=True)

    def action_move_selected_cells_up(self) -> None:
        start_id, end_id = self._get_selected_cells_range()
        if start_id > 0:
            cells = list(self.cells)
            cell_to_move = cells[start_id - 1]
            cell_to_move.remove_class("above_focused", update=False).add_class("below_focused")
            cells.remove(cell_to_move)
            cells.insert(end_id, cell_to_move)
            mapping = {cell: i for i, cell in enumerate(cells)}
            mapping.update({self.add_cell_button: len(cells)})
            self.scroll.sort_children(key=mapping.get)
            self.focused_cell_id -= 1
            self.start_cell_id -= 1
            self.screen.scroll_to_widget(self.cells[self.focused_cell_id])
            self.unsaved = True

    def action_move_selected_cells_down(self) -> None:
        start_id, end_id = self._get_selected_cells_range()
        if end_id + 1 < len(self.cells):
            cells = list(self.cells)
            cell_to_move = cells[end_id + 1]
            cell_to_move.remove_class("below_focused", update=False).add_class("above_focused")
            cells.remove(cell_to_move)
            cells.insert(start_id, cell_to_move)
            mapping = {cell: i for i, cell in enumerate(cells)}
            mapping.update({self.add_cell_button: len(cells)})
            self.scroll.sort_children(key=mapping.get)
            self.focused_cell_id += 1
            self.start_cell_id += 1
            self.screen.scroll_to_widget(self.cells[self.focused_cell_id])
            self.unsaved = True

    async def action_insert_cell_above(self) -> None:
        start_id, end_id = self._get_selected_cells_range()
        new_cell = CodeCell(classes="above_focused")
        await self.scroll.mount(new_cell, before=start_id)
        self._focus_cell(new_cell)
        self.unsaved = True

    async def action_insert_cell_below(self) -> None:
        start_id, end_id = self._get_selected_cells_range()
        new_cell = CodeCell(classes="below_focused")
        await self.scroll.mount(new_cell, after=self.focused_cell_id)
        self._focus_cell(new_cell)
        self.unsaved = True

    async def action_insert_cell_at_end(self) -> None:
        new_cell = CodeCell(classes="below_focused")
        await self.scroll.mount(new_cell, before=self.add_cell_button)
        self._focus_cell(new_cell)
        self.unsaved = True

    def action_copy_selected_cells(self) -> None:
        start_id, end_id = self._get_selected_cells_range()
        self.copied_cells_nbformat = [cell.to_nbformat() for cell in self.cells[start_id : end_id + 1]]

    async def action_cut_selected_cells(self) -> None:
        start_id, end_id = self._get_selected_cells_range()
        self.copied_cells_nbformat = [cell.to_nbformat() for cell in self.cells[start_id : end_id + 1]]
        self.cell_deletion_stack.append(self.CellDeletion(start_id, self.copied_cells_nbformat))
        self.set_focus(None)
        await self.scroll.remove_children(self.cells[start_id : end_id + 1])
        if not self.cells:
            # Ensure there is at least one cell
            new_cell = CodeCell(classes="focused")
            await self.scroll.mount(new_cell, before=0)
        self._focus_cell(self.cells[min(start_id, len(self.cells) - 1)])
        self.unsaved = True

    async def action_paste_cells_below(self) -> None:
        _, end_id = self._get_selected_cells_range()
        new_cells = [Cell.from_nbformat(node).add_class("below_focused") for node in self.copied_cells_nbformat]
        await self.scroll.mount(*new_cells, after=end_id)
        if new_cells:
            self._focus_cell(new_cells[-1])
            self.unsaved = True

    async def action_paste_cells_above(self) -> None:
        start_id, _ = self._get_selected_cells_range()
        new_cells = [Cell.from_nbformat(node).add_class("above_focused") for node in self.copied_cells_nbformat]
        await self.scroll.mount(*new_cells, before=self.focused_cell_id)
        if new_cells:
            self._focus_cell(new_cells[0])
            self.unsaved = True

    async def action_undo_cell_deletion(self) -> None:
        if len(self.cell_deletion_stack) > 0:
            restore = self.cell_deletion_stack.pop()
            new_cells = [Cell.from_nbformat(nbformat) for nbformat in restore.nbformats]
            assert restore.position <= len(self.cells)
            await self.scroll.mount(*new_cells, before=restore.position)
            self._focus_cell(new_cells[-1])
            self.unsaved = True

    def double_press(f):
        """Decorator to activate action if a key has been double pressed"""

        async def new_f(self, *args, **kwargs):
            if self.repeat_key_count == 2:
                self.repeat_key = None
                await f(self, *args, **kwargs)

        return new_f

    @double_press
    async def action_try_delete_selected_cells(self) -> None:
        await self.action_delete_selected_cells()

    async def action_delete_selected_cells(self) -> None:
        start_id, end_id = self._get_selected_cells_range()
        self.cell_deletion_stack.append(
            self.CellDeletion(start_id, [cell.to_nbformat() for cell in self.cells[start_id : end_id + 1]])
        )
        self.set_focus(None)
        await self.scroll.remove_children(self.cells[start_id : end_id + 1])
        if not self.cells:
            # Ensure there is at least one cell
            new_cell = CodeCell(classes="focused")
            await self.scroll.mount(new_cell, before=0)
        self._focus_cell(self.cells[min(start_id, len(self.cells) - 1)])
        self.unsaved = True

    async def action_merge_selected_cells(self) -> None:
        start_id, end_id = self._get_selected_cells_range()
        if start_id == end_id:
            if end_id + 1 == len(self.cells):
                return
            # merge with the cell below
            end_id += 1
        self.cells[start_id].source.text = "\n\n".join(cell.source.text for cell in self.cells[start_id : end_id + 1])
        self.cell_deletion_stack.append(
            self.CellDeletion(start_id + 1, [cell.to_nbformat() for cell in self.cells[start_id + 1 : end_id + 1]])
        )
        await self.scroll.remove_children(self.cells[start_id + 1 : end_id + 1])
        self._focus_cell(self.cells[start_id])
        self.unsaved = True

    def action_save_notebook(self) -> None:
        self.nb = nbformat.v4.new_notebook(
            metadata=dict(
                kernelspec=dict(
                    name=self.kernel_manager.kernel_name,
                    language=self.kernel_manager.kernel_spec.language,
                    display_name=self.kernel_manager.kernel_spec.display_name,
                )
            ),
            cells=[cell.to_nbformat() for cell in self.cells],
        )
        nbformat.write(self.nb, self.nbfile)
        self.unsaved = False
        self.notify("Notebook Saved")

    def action_toggle_line_numbers(self) -> None:
        start_id, end_id = self._get_selected_cells_range()
        for cell in self.cells[start_id : end_id + 1]:
            cell.source.show_line_numbers = not cell.source.show_line_numbers

    def action_set_line_numbers_in_all_cells(self, to: None | bool) -> None:
        # None to toggle
        self.show_line_numbers = not self.show_line_numbers if to is None else to

    def action_toggle_output(self, range: Range) -> None:
        for cell in self._get_range_cells(range):
            if isinstance(cell, CodeCell):
                cell.collapsed = not cell.collapsed
                self.unsaved = True

    def action_toggle_output_scrolling(self, range: Range) -> None:
        for cell in self._get_range_cells(range):
            if isinstance(cell, CodeCell):
                cell.scrolled = not cell.scrolled
                self.unsaved = True

    def action_toggle_help(self) -> None:
        if self.screen.query("HelpPanel"):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()

    def action_interrupt_kernel(self) -> None:
        self.notify("interrupting kernel")
        self.kernel_manager.interrupt_kernel()

    @double_press
    async def action_try_interrupt_kernel(self) -> None:
        self.action_interrupt_kernel()

    def action_restart_kernel(self) -> None:
        self.notify("restarting kernel")
        # Cancell all the tasks
        self.cancel_kernel_tasks()
        self.kernel_manager.restart_kernel()
        assert len(self.kernel_access_queue) == 0
        self.queue_for_kernel(self._initialize_kernel)

    @double_press
    async def action_try_restart_kernel(self) -> None:
        self.action_restart_kernel()

    def action_restart_and_run_all(self) -> None:
        self.action_restart_kernel()
        self.action_run_cells("all")

    async def action_split_cell_at_cursor(self) -> None:
        focused_cell = self.cells[self.focused_cell_id]
        start = focused_cell.source.document.get_index_from_location(focused_cell.source.selection.start)
        end = focused_cell.source.document.get_index_from_location(focused_cell.source.selection.end)
        start, end = min(start, end), max(start, end)
        chunks = (focused_cell.source.text[:start], focused_cell.source.text[start:end], focused_cell.source.text[end:])

        def strip_blank_lines(s: str) -> str:
            lines = s.split("\n")
            start = 0
            while start < len(lines) and not lines[start].strip():
                start += 1
            end = len(lines) - 1
            while end >= start and not lines[end].strip():
                end -= 1
            return "\n".join(lines[start : end + 1])

        nonempty_chunks = list(filter(lambda s: len(s) > 0, map(strip_blank_lines, chunks)))

        if len(nonempty_chunks) > 1:
            new_cells = [type(focused_cell)(chunk, classes="above_focused") for chunk in nonempty_chunks[:-1]]
            await self.scroll.mount(*new_cells, before=self.focused_cell_id)
            focused_cell.source.text = nonempty_chunks[-1]
            self.focused_cell_id += len(nonempty_chunks) - 1
            self.unsaved = True
