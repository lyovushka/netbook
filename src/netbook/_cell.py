from __future__ import annotations

import abc
import asyncio
import base64
import dataclasses
import io
import typing_extensions as tp

import nbformat

import pyvips

import rich.ansi
import rich.text

import textual.app
import textual.binding
import textual.containers
import textual.message
import textual.widgets.text_area

import textual_image.widget

import zmq

from netbook._text_area import CellTextArea, CodeTextArea

if tp.TYPE_CHECKING:
    from netbook import JupyterTextualApp


class Counter(textual.widgets.Static):
    """Displays input or output execution count."""

    execution_count: textual.reactive.reactive[int | str] = textual.reactive.reactive(" ")
    format: textual.reactive.reactive[str] = textual.reactive.reactive("")

    def watch_execution_count(self, execution_count) -> None:
        self.update(self.format.format(execution_count))

    def watch_format(self, format) -> None:
        self.update(format.format(self.execution_count))


class Output(textual.containers.Container):
    """Base class for code cell output."""

    @dataclasses.dataclass
    class Resized(textual.message.Message):
        """Pass on resize events to parents."""

        output: Output
        size: textual.geometry.Size

    @abc.abstractmethod
    def to_nbformat(self) -> nbformat.NotebookNode:
        raise NotImplementedError

    def on_resize(self, event: textual.events.Resize) -> None:
        self.post_message(Output.Resized(self, event.size))

    @staticmethod
    def ansi_to_rich(text: str, strip: bool = True) -> rich.text.Text:
        """Convet ansi escaped sequences to rich text.

        Work around some issues with rich.text.Text.from_ansi and optionally strip blank lines from the start and end."""

        # splitlines - used by rich.text.Text.from_ansi splits on "\r" too.
        # E.g. tqdm relies on "\r" to rerender on the same line. So we split on "\n"-only.
        lines = text.split("\n")
        start = 0
        while strip and start < len(lines) and not lines[start].strip():
            start += 1
        end = len(lines) - 1
        while strip and end >= start and not lines[end].strip():
            end -= 1
        decoder = rich.ansi.AnsiDecoder()
        return rich.text.Text("\n").join(decoder.decode_line(line) for line in lines[start : end + 1])


class Stream(Output):
    """Stream output in notebook."""

    text: textual.reactive.reactive[str] = textual.reactive.reactive("", recompose=True)

    def __init__(self, name: str, text: str = "") -> None:
        super().__init__(classes=name)
        self.stream_name = name
        self.text = text

    @tp.override
    def to_nbformat(self) -> nbformat.NotebookNode:
        return nbformat.v4.new_output(output_type="stream", name=self.stream_name, text=self.text)

    def compose(self) -> tp.Iterable[textual.widgets.Widget]:
        with textual.containers.HorizontalScroll():
            yield textual.widgets.Static(self.ansi_to_rich(self.text))


class DisplayData(Output):
    """Cell output of type display_data."""

    def __init__(self, data: dict[str, tp.Any], metadata: dict[str, tp.Any]) -> None:
        super().__init__()
        self.data, self.metadata = data, metadata
        self.app: JupyterTextualApp

    @tp.override
    def to_nbformat(self) -> nbformat.NotebookNode:
        return nbformat.v4.new_output(output_type="display_data", data=self.data, metadata=self.metadata)

    def _find_image(self):
        for key in self.data:
            if key.startswith("image/"):
                return key
        return None

    def compose(self) -> tp.Iterable[textual.widgets.Widget]:
        with textual.containers.HorizontalScroll():
            image_key = self._find_image()
            if image_key:
                image_bytes = (
                    pyvips.Image.svgload_buffer(self.data[image_key].encode()).pngsave_buffer()
                    if image_key == "image/svg+xml"
                    else base64.b64decode(self.data[image_key])
                )
                image = self.app.image_class(io.BytesIO(image_bytes))
                # We'll set the width/height explicitly since automatically setting it seems hard / impossible.
                cell_size = textual_image.widget.get_cell_size()
                image.styles.width = round(image._image_width / cell_size.width)
                image.styles.height = round(image._image_height / cell_size.height)
                yield image
            elif self.data.get("text/markdown"):
                yield textual.widgets.Markdown(self.data["text/markdown"])
            elif self.data.get("text/plain"):
                yield textual.widgets.Static(self.ansi_to_rich(self.data["text/plain"]))


class ExecuteResult(DisplayData):
    """Cell output of type execute_result."""

    def __init__(self, execution_count: int, data: dict[str, tp.Any], metadata: dict[str, tp.Any]) -> None:
        super().__init__(data, metadata)
        self.execution_count = execution_count

    @tp.override
    def to_nbformat(self) -> nbformat.NotebookNode:
        return nbformat.v4.new_output(
            output_type="execute_result", execution_count=self.execution_count, data=self.data, metadata=self.metadata
        )


class Error(Output):
    """Cell output of type error."""

    def __init__(self, ename: str, evalue: str, traceback: list[str]) -> None:
        super().__init__()
        self.ename, self.evalue, self.traceback = ename, evalue, traceback

    @tp.override
    def to_nbformat(self) -> nbformat.NotebookNode:
        return nbformat.v4.new_output(
            output_type="error", ename=self.ename, evalue=self.evalue, traceback=self.traceback
        )

    def compose(self) -> tp.Iterable[textual.widgets.Widget]:
        with textual.containers.HorizontalScroll():
            yield textual.widgets.Static(rich.text.Text.from_ansi("\n".join(self.traceback)))


class Cell(textual.containers.Container, can_focus=True):
    """Abstract base class for a notebook cell."""

    BINDINGS = [
        textual.binding.Binding("enter", "edit_mode", "enter edit mode"),
        textual.binding.Binding("escape", "command_mode", "enter command mode"),
    ]

    @dataclasses.dataclass
    class Focused(textual.message.Message):
        cell: Cell
        input: bool = False

    @abc.abstractmethod
    def to_nbformat(self) -> nbformat.NotebookNode:
        raise NotImplementedError

    @abc.abstractmethod
    def cell_type(self) -> str:
        raise NotImplementedError

    @staticmethod
    def from_nbformat(node: nbformat.NotebookNode):
        match node.cell_type:
            case "code":
                cell = CodeCell(source=node.source)
                cell.execution_count = node.execution_count or " "
                cell.last_executed = node.source
                if "metadata" in node:
                    if "collapsed" in node.metadata:
                        cell.collapsed = node.metadata.collapsed
                    if "scrolled" in node.metadata and node.metadata.scrolled != "auto":
                        cell.scrolled = node.metadata.scrolled
                for output in node.outputs:
                    match output.output_type:
                        case "stream":
                            cell.add_output(Stream(output.name, output.text))
                        case "display_data":
                            cell.add_output(DisplayData(output.data, output.metadata))
                        case "execute_result":
                            cell.add_output(ExecuteResult(output.execution_count, output.data, output.metadata))
                        case "error":
                            cell.add_output(Error(output.ename, output.evalue, output.traceback))
                        case _:
                            raise RuntimeError(f"Unknown output type {output.output_type}")
            case "markdown":
                cell = MarkdownCell(source=node.source)
            case "raw":
                cell = RawCell(source=node.source)
            case _:
                raise RuntimeError(f"Unknown cell type {node.cell_type}")
        return cell

    def __init__(self, source: textual.widgets.TextArea, *, classes: str | None = None) -> None:
        """Constructor.

        Parameters
        ----------
        source: TextArea
            Editor widget for this cell.
        """
        self.app: JupyterTextualApp
        super().__init__(classes=classes)
        self.source = source

    def on_descendant_focus(self, event: textual.events.DescendantFocus) -> None:
        self.post_message(Cell.Focused(self, input=self.source.has_focus_within))

    def on_focus(self, message: textual.events.Focus):
        self.post_message(Cell.Focused(self))

    def check_action(self, action: str, parameters) -> bool | None:
        if action == "edit_mode":
            return not self.source.has_focus_within
        if action == "command_mode":
            return self.source.has_focus_within
        return True

    def action_edit_mode(self) -> None:
        self.source.focus(scroll_visible=False)

    def action_command_mode(self) -> None:
        self.focus(scroll_visible=False)

    @abc.abstractmethod
    def execute(self) -> None:
        """Execute this cell."""
        raise NotImplementedError


class MarkdownCell(Cell):
    edit_mode: textual.reactive.reactive[bool] = textual.reactive.reactive(True, layout=True)

    def watch_edit_mode(self, new_value: bool) -> None:
        if new_value:
            self.source.remove_class("hidden")
            self.markdown.add_class("hidden")
        else:
            self.markdown.update(self.source.text)
            self.source.add_class("hidden")
            self.markdown.remove_class("hidden")

    def __init__(self, source: str = "", *, classes: str | None = None) -> None:
        super().__init__(
            CellTextArea.code_editor(source, language="markdown", soft_wrap=True, highlight_cursor_line=False),
            classes=classes,
        )
        self.markdown = textual.widgets.Markdown()

    def on_text_area_changed(self, event: textual.widgets.TextArea.Changed):
        if not self.edit_mode:
            self.markdown.update(event.text_area.text)

    @tp.override
    def to_nbformat(self) -> nbformat.NotebookNode:
        return nbformat.v4.new_markdown_cell(source=self.source.text)

    @tp.override
    def cell_type(self) -> str:
        return "markdown"

    def compose(self) -> tp.Iterable[textual.widgets.Widget]:
        with textual.containers.Horizontal():
            yield Counter()
            yield self.source
            yield self.markdown

    def on_click(self, message: textual.events.Click) -> None:
        if message.chain > 1:
            self.action_edit_mode()

    @tp.override
    def execute(self) -> None:
        self.edit_mode = False

    @tp.override
    def action_edit_mode(self) -> None:
        self.edit_mode = True
        super().action_edit_mode()


class DoubleClickButton(textual.widgets.Button, can_focus=False):
    """A button that can be double clicked."""

    @dataclasses.dataclass
    class DoublePressed(textual.events.Message):
        button: DoubleClickButton

    def __init__(self, label: str, *, tooltip: str) -> None:
        super().__init__(label, tooltip=tooltip)

    async def on_click(self, event: textual.events.Click) -> None:
        event.stop()
        event.prevent_default()
        if not self.has_class("-active") and event.chain == 1:
            self.press()
        elif event.chain == 2:
            # We don't check for "-active" here since on_click is called twice for double click.
            self.double_press()

    def double_press(self) -> tp.Self:
        if self.display and not self.disabled:
            self._start_active_affect()
            self.post_message(DoubleClickButton.DoublePressed(self))
        return self


class CodeCell(Cell):
    scrolled: textual.reactive.reactive[bool | None] = textual.reactive.reactive(None)  # None for auto
    collapsed: textual.reactive.reactive[bool] = textual.reactive.reactive(False)
    execution_count: textual.reactive.reactive[int | str] = textual.reactive.reactive(" ")
    counter_format: textual.reactive.reactive[str] = textual.reactive.reactive("In [{}]:")

    @dataclasses.dataclass
    class NewOutput(textual.events.Event):
        code_cell: CodeCell

    def watch_scrolled(self, scrolled: bool | None) -> None:
        if scrolled or (scrolled is None and sum(self.output_heights.values()) > 105):
            self.output_area.add_class("scrolled")
            self.scroll_button.tooltip = "click to unscroll output; double click to hide"
        else:
            self.output_area.remove_class("scrolled")
            self.scroll_button.tooltip = "click to scroll output; double click to hide"

    def watch_collapsed(self, collapsed: bool) -> None:
        if collapsed:
            self.output_area.remove_class("noncollapsed")
            self.output_area.add_class("collapsed")
        else:
            self.output_area.remove_class("collapsed")
            self.output_area.add_class("noncollapsed")

    def watch_execution_count(self, execution_count: int | str) -> None:
        self.counter_format = "In [{}]:"

    def __init__(self, source: str = "", *, classes: str | None = None) -> None:
        language = self.app.kernel_manager.kernel_spec.language.lower()
        initial_language = language if language in textual.widgets.text_area.BUILTIN_LANGUAGES else None
        text_area = CodeTextArea.code_editor(source, language=initial_language, highlight_cursor_line=False)
        if language not in textual.widgets.text_area.BUILTIN_LANGUAGES and self.app.language_highlights_query:
            text_area.register_language(language, self.app.tree_sitter_language, self.app.language_highlights_query)
            text_area.language = language

        super().__init__(text_area, classes=classes)
        self.output_area = textual.containers.Container(classes="codeoutput noncollapsed")
        self.all_outputs: list[Output] = []
        self.all_outputs_container = textual.containers.Vertical()
        self.scroll_button = DoubleClickButton("", tooltip="click to scroll output; double click to hide")
        self.expand_button = textual.widgets.Button("...", tooltip="click to expand output")
        self.scroll_button.styles.line_pad = 0  # For some reason can't set this in css
        self.output_heights = {}
        self.n_active_executions = 0
        self.last_executed = ""

    def on_double_click_button_double_pressed(self, event: DoubleClickButton.DoublePressed):
        assert not self.collapsed
        self.collapsed = True
        self.focus(False)

    def on_button_pressed(self, event: textual.widgets.Button.Pressed):
        match event.button:
            case self.scroll_button:
                self.scrolled = not self.output_area.has_class("scrolled")
            case self.expand_button:
                assert self.collapsed
                self.collapsed = False
                self.scrolled = None
                self.focus(False)
            case _:
                assert False

    @tp.override
    def to_nbformat(self) -> nbformat.NotebookNode:
        return nbformat.v4.new_code_cell(
            source=self.source.text,
            execution_count=self.execution_count if isinstance(self.execution_count, int) else None,
            outputs=[output.to_nbformat() for output in self.all_outputs],
            metadata={"collapsed": self.collapsed, "scrolled": "auto" if self.scrolled is None else self.scrolled},
        )

    @tp.override
    def cell_type(self) -> str:
        return "code"

    def on_text_area_changed(self, message: textual.widgets.TextArea.Changed) -> None:
        if self.execution_count != " " and message.text_area.text != self.last_executed:
            self.counter_format = "In∙[{}]:"
        else:
            self.counter_format = "In [{}]:"

    def on_output_resized(self, message: Output.Resized) -> None:
        self.output_heights[message.output] = message.size.height

        # update button label
        label = ""
        for output in self.all_outputs:
            if isinstance(output, ExecuteResult):
                label += f"Out\\[{output.execution_count}]:"
                break
            else:
                label += "\n" * self.output_heights.get(output, 0)
        if label.strip():
            self.scroll_button.label = label

        # update scrolled if necessary
        self.watch_scrolled(self.scrolled)

    async def clear_outputs(self):
        if self.is_mounted:
            self.all_outputs_container.remove_children()
        self.all_outputs = []

    def add_output(self, output: Output) -> textual.widget.AwaitMount:
        if self.n_active_executions <= 1:
            self.all_outputs.append(output)
            if self.is_mounted:
                self.post_message(self.NewOutput(self))
                return self.all_outputs_container.mount(output)
            else:
                return textual.widget.AwaitMount(self, [])

    def compose(self) -> tp.Iterable[textual.widgets.Widget]:
        with textual.containers.Horizontal():
            yield Counter(classes="input").data_bind(CodeCell.execution_count, format=CodeCell.counter_format)
            yield self.source
        with self.output_area:
            yield self.expand_button
            with textual.containers.Horizontal():
                yield self.scroll_button
                with self.all_outputs_container:
                    for output in self.all_outputs:
                        yield output

    async def _parse_message(self, message: dict[str, tp.Any]) -> None:
        self.app.log.info(f"got message {message}")
        header = message["header"]
        content = message["content"]
        await_mount = None
        match header["msg_type"]:
            case "execute_result":
                await_mount = self.add_output(
                    ExecuteResult(content["execution_count"], content["data"], content["metadata"])
                )
            case "display_data":
                await_mount = self.add_output(DisplayData(content["data"], content["metadata"]))
            case "execute_reply":
                if self.n_active_executions == 1:
                    # if the cell has been rerun, don't set the execution_count
                    self.execution_count = content["execution_count"]
                for payload in content["payload"]:
                    match payload["source"]:
                        case "page":
                            await_mount = self.add_output(DisplayData(payload["data"], {}))
                if content["status"] != "ok":
                    raise RuntimeError(content["ename"])
            case "stream":
                if (
                    self.all_outputs
                    and isinstance(self.all_outputs[-1], Stream)
                    and self.all_outputs[-1].stream_name == content["name"]
                ):
                    self.all_outputs[-1].text = self.all_outputs[-1].text + content["text"]
                    self.post_message(self.NewOutput(self))
                else:
                    await_mount = self.add_output(Stream(name=content["name"], text=content["text"]))
            case "error":
                await_mount = self.add_output(Error(content["ename"], content["evalue"], content["traceback"]))
        if await_mount:
            await await_mount

            def scroll_callback(widget):
                if not self.screen.can_view_entire(widget):
                    self.screen.scroll_to_widget(widget, center=True, force=False)

            self.all_outputs[-1].call_after_refresh(scroll_callback, self.all_outputs[-1])

    @tp.override
    def execute(self) -> None:
        self.output_heights = {}
        # TODO: do we need to await this?
        self.all_outputs_container.remove_children()
        self.all_outputs = []
        self.watch_scrolled(self.scrolled)  # Updates `scrolled` class.
        self.collapsed = False
        self.scroll_button.label = ""
        if not self.source.text:
            self.execution_count = " "
            return
        self.n_active_executions += 1
        self.execution_count = "*"
        self.last_executed = self.source.text

        def task_done(task: asyncio.Task):
            self.n_active_executions -= 1
            if self.execution_count == "*" and (task.cancelled() or task.exception()):
                self.execution_count = " "

        # Snap the code at this time
        code = self.source.text
        self.app.queue_for_kernel(self._execute, code).add_done_callback(task_done)

    async def _execute(self, code: str) -> None:
        kernel_client = self.app.kernel_client

        msg_id = kernel_client.execute(code)

        poller = zmq.asyncio.Poller()
        iopub_socket = kernel_client.iopub_channel.socket
        poller.register(iopub_socket, zmq.POLLIN)

        # wait for output and redisplay it
        while True:
            if not self.app.kernel_manager.is_alive():
                raise TimeoutError

            events = dict(await poller.poll(timeout=1))
            if iopub_socket not in events:
                continue

            msg = await kernel_client.iopub_channel.get_msg(timeout=1)

            if msg["parent_header"].get("msg_id") != msg_id:
                # not from my request
                continue
            await self._parse_message(msg)

            # stop on idle
            if msg["header"]["msg_type"] == "status" and msg["content"]["execution_state"] == "idle":
                break

        # output is done, get the reply
        res = await kernel_client._recv_reply(msg_id, timeout=1)
        await self._parse_message(res)


class RawCell(Cell):
    def __init__(self, source: str = "", *, classes: str | None = None) -> None:
        super().__init__(CodeTextArea.code_editor(source, soft_wrap=True), classes=classes)

    @tp.override
    def to_nbformat(self) -> nbformat.NotebookNode:
        return nbformat.v4.new_raw_cell(source=self.source.text)

    @tp.override
    def cell_type(self) -> str:
        return "raw"

    def compose(self) -> tp.Iterable[textual.widgets.Widget]:
        with textual.containers.Horizontal():
            yield Counter()
            yield self.source

    @tp.override
    def execute(self) -> None:
        pass
