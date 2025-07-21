import netbook
import asyncio


async def test_text_area(pilot, mocker):
    app: netbook.JupyterTextualApp = pilot.app
    await app.action_run_cell_and_select_below()
    await pilot.pause()
    assert len(app.cells) == 2
    assert app.focused_cell_id == 1
    assert app.cells[1].has_class("input_focused")

    # Test moving up from text area
    await pilot.press("up")
    await pilot.pause()
    assert app.focused_cell_id == 0

    await app.action_run_cell_and_insert_below()
    await pilot.pause()
    assert len(app.cells) == 3
    assert app.focused_cell_id == 1
    assert app.cells[1].has_class("input_focused")

    # Test moving down from text area
    await pilot.press("down")
    await pilot.pause()
    assert app.focused_cell_id == 2

    source: netbook._text_area.CodeTextArea = app.cells[2].source
    await pilot.press("a")
    assert source.text == "a"

    # Test autocomplete on single suggestion
    app.kernel_client._recv_reply = mocker.AsyncMock(return_value={"content": {"cursor_start": 0, "matches": ["asdf"]}})
    await pilot.press("tab")
    assert not source.completer.visible
    assert source.text == "asdf"

    # Test multiple suggestions
    app.kernel_client._recv_reply = mocker.AsyncMock(
        return_value={"content": {"cursor_start": 0, "matches": ["asdfasdf", "asdffdsa"]}}
    )
    await pilot.press("tab")
    assert source.completer.visible
    assert source.text == "asdf"

    # Test the pressing some keys doesn't close the completer
    await pilot.press("down")
    await pilot.pause()
    assert source.completer.visible

    # Test clicking on an option
    await pilot.click(source.completer, offset=(1, 1))
    await pilot.pause()
    assert not source.completer.visible
    assert source.text == "asdffdsa"

    # Test dismissing completer on unrecognized key
    await pilot.press("tab")
    await pilot.pause()
    assert source.completer.visible
    await pilot.press("left")
    await pilot.pause()
    assert not source.completer.visible

    # Test reopening completer on printable character
    await pilot.press("q")
    await pilot.press("tab")
    await pilot.pause()
    assert app.kernel_client._recv_reply.call_count == 3
    assert source.text == "asdffdsqa"
    assert source.completer.visible

    # Test empty response from kernel
    app.kernel_client._recv_reply = mocker.AsyncMock(return_value={"content": {"cursor_start": 0, "matches": []}})
    await pilot.press("q")
    await pilot.press("tab")
    await pilot.pause()
    assert not source.completer.visible
    assert source.text == "asdffdsqqa"
    assert source.has_focus

    # Test showing inspector
    app.kernel_client._recv_reply = mocker.AsyncMock(
        # long response will force scrollbars
        return_value={"content": {"data": {"text/plain": ("a" * 90 + "\n") * 40}}}
    )
    await pilot.press("shift+tab")
    await pilot.pause()
    assert source.inspect.visible
    await pilot.press("left")
    await pilot.pause()
    assert source.inspect.visible
    await pilot.press("a")
    await pilot.pause()
    assert not source.inspect.visible

    # Test no inspect from kernel
    app.kernel_client._recv_reply = mocker.AsyncMock(return_value={"content": {"data": {}}})
    await pilot.press("shift+tab")
    await pilot.pause()
    assert not source.inspect.visible

    # Test kernel crash / bad response
    app.kernel_client._recv_reply = mocker.AsyncMock(return_value="asdf")
    await pilot.press("shift+tab")
    await pilot.pause()
    assert not source.inspect.visible

    # Test clicking outside
    app.kernel_client._recv_reply = mocker.AsyncMock(return_value={"content": {"data": {"text/plain": "help"}}})
    await pilot.press("shift+tab")
    await pilot.pause()
    assert source.inspect.visible
    assert source.inspect.has_focus
    await pilot.click(source, offset=(0, 0))
    await pilot.pause()
    assert not source.inspect.visible

    # Test kernel busy
    app.kernel_access_queue.add(asyncio.Future())
    app.kernel_client._recv_reply = mocker.AsyncMock()
    await pilot.press("a")  # move the cursor from the start
    await pilot.press("shift+tab")
    await pilot.pause()
    assert not source.inspect.visible
    assert app.kernel_client._recv_reply.call_count == 0
    app.kernel_access_queue = {}
