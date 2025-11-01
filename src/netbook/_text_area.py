from __future__ import annotations

import abc
import asyncio
import dataclasses
import re
import typing_extensions as tp

import rich.text

import textual.app
import textual.binding
import textual.containers
import textual.reactive
import textual.widgets

if tp.TYPE_CHECKING:
    from netbook import JupyterTextualApp


class PopUpMixin:
    # TODO: unable to declare "visisble" here due to multiple inheritance?
    def watch_visible(self, visible: True) -> None:
        if visible:
            self.remove_class("hidden")
            self.focus(scroll_visible=False)
        else:
            self.add_class("hidden")

    def _on_focus(self, event: textual.events.Focus) -> None:
        self.parent.has_focus = True

    def _on_blur(self, event: textual.events.Blur) -> None:
        if self.visible:
            self.parent.has_focus = False
            self.visible = False

    def action_dismiss(self) -> None:
        self.parent.has_focus = True
        self.visible = False
        self.parent.focus(scroll_visible=False)

    @abc.abstractmethod
    def estimate_height(self) -> int:
        pass


class Completer(textual.widgets.OptionList, PopUpMixin):
    visible: textual.reactive.reactive[bool] = textual.reactive.reactive(False)

    BINDINGS = [
        textual.binding.Binding("backspace, escape", "dismiss", "Dismiss"),
    ]

    def get_handle_keys(self) -> set[str]:
        return {"backspace", "down", "end", "enter", "escape", "home", "pagedown", "pageup", "up"}

    def __init__(self) -> None:
        super().__init__(self, classes="hidden")

    def action_select(self) -> None:
        super().action_select()
        self.visible = False
        self.parent.focus(scroll_visible=False)

    @tp.override
    def estimate_height(self) -> int:
        # TODO: add border shmorder
        assert self.styles.max_height.is_cells
        return min(self.styles.max_height.value, self.option_count)


class Inspect(textual.containers.ScrollableContainer, PopUpMixin, can_focus=True):
    visible: textual.reactive.reactive[bool] = textual.reactive.reactive(False)

    BINDINGS = [
        textual.binding.Binding("escape", "dismiss", "Dismiss"),
    ]

    def __init__(self) -> None:
        super().__init__(classes="hidden")
        self.contents = textual.widgets.Static()

    def compose(self) -> textual.app.ComposeResult:
        yield self.contents

    def update(self, contents: textual.visual.Visual) -> None:
        self.scroll_home(animate=False, immediate=True)
        self.contents.update(contents)

    def get_handle_keys(self) -> set[str]:
        keys = {"escape"}
        if self.allow_vertical_scroll:
            keys.update(["up", "down", "pageup", "pagedown", "home", "end"])
        if self.allow_horizontal_scroll:
            keys.update(["left", "right", "ctrl+pageup", "ctrl+pagedown", "home", "end"])
        return keys

    @tp.override
    def estimate_height(self) -> int:
        assert self.styles.max_height.is_cells
        return min(
            self.styles.max_height.value,
            len(str(self.contents.content).splitlines())
            + self.styles.border.spacing.top
            + self.styles.border.spacing.bottom,
        )


class CellTextArea(textual.widgets.TextArea):
    @dataclasses.dataclass
    class CursorOutBottom(textual.message.Message):
        text_area: CellTextArea

    @dataclasses.dataclass
    class CursorOutTop(textual.message.Message):
        text_area: CellTextArea

    def _on_key(self, event: textual.events.Key) -> None:
        if event.key == "escape":
            # Let it be handled upstream
            event.prevent_default()

    @tp.override
    def action_cursor_down(self, select: bool = False) -> None:
        old_location = self.cursor_location
        super().action_cursor_down(select)
        if not select and self.cursor_location == old_location:
            self.post_message(CellTextArea.CursorOutBottom(self))

    @tp.override
    def action_cursor_up(self, select: bool = False) -> None:
        old_location = self.cursor_location
        super().action_cursor_up(select)
        if not select and self.cursor_location == old_location:
            self.post_message(CellTextArea.CursorOutTop(self))


class CodeTextArea(CellTextArea):
    """Extends text area with jupyter completions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.completer = Completer()
        self.inspect = Inspect()
        self.app: JupyterTextualApp

    def compose(self) -> textual.app.ComposeResult:
        yield self.completer
        yield self.inspect

    def _on_mount(self, event: textual.events.Mount) -> None:
        # By default TextArea resets its selection when screen selection starts.
        # This is a bit inconsistent since two text areas can still have their own selections.
        # It also causes problems because we scroll to the cursor when the selection changes in a text area.
        # We disable this behaviour by unsubscribing here.
        self.call_later(lambda: self.screen.text_selection_started_signal.unsubscribe(self))

    # TODO: type annotate
    def with_kernel(f):
        async def new_f(self, *args, **kwargs):
            if len(self.app.kernel_access_queue) > 0:
                # We don't want to wait
                self.inspect.visible = False
                self.completer.visible = False
                self.focus(scroll_visible=False)
                return

            task = self.app.queue_for_kernel(f, self, *args, **kwargs)
            try:
                await task
            except (Exception, asyncio.CancelledError):
                self.inspect.visible = False
                self.completer.visible = False
                self.focus(scroll_visible=False)

        return new_f

    def _compute_pop_offset(self, popup: PopUpMixin, virtual_cursor_position: tp.Tuple[int, int]) -> tp.Tuple[int, int]:
        start_x, start_y = self.wrapped_document.location_to_offset(virtual_cursor_position)
        estimated_height = popup.estimate_height()
        # offset_y = 1 if we put below the curser, negative otherwise
        offset_y = (
            1 if self.screen.region.height - self.cursor_screen_offset.y - estimated_height > 0 else -estimated_height
        )
        return (start_x - self.scroll_offset[0] + self.gutter_width - 1, start_y - self.scroll_offset[1] + offset_y)

    @with_kernel
    async def _complete_from_kernel(self, autoinsert: bool) -> None:
        """
        Parameters:
        -----------
        autoinsert: bool
            if True the result is automatically inserted if the completion is unique
        """
        self.inspect.visible = False
        cursor_pos = self.document.get_index_from_location(self.cursor_location)
        msg_id = self.app.kernel_client.complete(self.text, cursor_pos)
        msg = await self.app.kernel_client._recv_reply(msg_id, 5)
        self.app.log.info(f"got message {msg}")
        self.replace_start = self.document.get_location_from_index(msg["content"]["cursor_start"])
        matches = msg["content"]["matches"]
        if not matches:
            textual.log("action dismiss")
            self.completer.action_dismiss()
            textual.log(f"{self.has_focus=}")
            return
        elif len(matches) == 1 and autoinsert:
            self.replace(matches[0], self.replace_start, self.cursor_location)
            self.completer.action_dismiss()
            return
        self.completer.visible = True
        self.completer.clear_options()
        self.completer.add_options(matches)
        self.completer.highlighted = 0
        self.completer.styles.offset = self._compute_pop_offset(self.completer, self.replace_start)
        self.completer.refresh(layout=True)

    @with_kernel
    async def _show_inspect(self):
        self.completer.visible = False
        cursor_pos = self.document.get_index_from_location(self.cursor_location)
        msg_id = self.app.kernel_client.inspect(self.text, cursor_pos)
        msg = await self.app.kernel_client._recv_reply(msg_id, 5)
        self.app.log.info(f"got message {msg}")
        if "text/plain" not in msg["content"]["data"]:
            self.inspect.action_dismiss()
            return
        self.inspect.update(rich.text.Text.from_ansi(msg["content"]["data"]["text/plain"]))
        self.inspect.visible = True
        self.inspect.styles.offset = self._compute_pop_offset(self.inspect, self.cursor_location)

    def _is_start_of_line(self):
        return not self.document.get_line(self.cursor_location[0])[: self.cursor_location[1]].strip()

    async def _on_key(self, event: textual.events.Key) -> None:
        if event.key == "shift+tab":
            if not self._is_start_of_line() and self.selection.is_empty:
                event.prevent_default()
                event.stop()
                await self._show_inspect()
        elif event.key == "tab":
            if not self._is_start_of_line() and self.selection.is_empty:
                event.prevent_default()
                event.stop()
                await self._complete_from_kernel(True)
        elif self.completer.visible:
            if event.is_printable and re.match("[%0-9a-z._/\\:~-]", event.character, re.I):
                self.call_later(self._complete_from_kernel, False)
            elif event.key in self.completer.get_handle_keys():
                event.prevent_default()
            else:
                self.completer.action_dismiss()
        elif self.inspect.visible:
            if event.key in self.inspect.get_handle_keys():
                event.prevent_default()
            else:
                self.inspect.action_dismiss()

    def on_option_list_option_selected(self, message: Completer.OptionSelected) -> None:
        self.replace(message.option.prompt, self.replace_start, self.cursor_location)

    def _on_mouse_down(self, event: textual.events.MouseDown) -> None:
        if self.completer.visible:
            # The parent captures mouse which prevents the completer from getting messages
            event.prevent_default()
