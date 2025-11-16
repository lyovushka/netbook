import netbook
import asyncio
import textual


async def test_non_code_cells(pilot):
    app: netbook.JupyterTextualApp = pilot.app
    assert app.cells[0].cell_type() == "code"
    assert app.cells[0].has_class("input_focused")
    assert not app.cells[0].check_action("edit_mode", None)
    assert app.cells[0].check_action("command_mode", None)
    assert app.cells[0].check_action("notify", None)

    app.cells[0].execute()
    assert app.cells[0].execution_count == " "

    await pilot.press("escape")
    await pilot.pause()
    assert not app.cells[0].has_class("input_focused")

    await pilot.press("r")
    await pilot.pause()
    assert app.cells[0].cell_type() == "raw"
    app.cells[0].execute()

    app.cell_type_selector.value = "markdown"
    await pilot.pause()
    await pilot.pause() # fixes the flakiness on windows.
    assert app.cells[0].cell_type() == "markdown"
    app.cells[0].execute()
    app.cells[0].source.text = "asdf"
    assert not app.cells[0].has_class("input_focused")
    await pilot.click("TextArea", times=2)
    await pilot.pause()
    assert app.cells[0].has_class("input_focused")


async def test_output_scroll_collapse(pilot_nb):
    pilot_nb: textual.pilot.Pilot
    app: netbook.JupyterTextualApp = pilot_nb.app
    assert app.cells[0].cell_type() == "code"
    assert app.cells[0].collapsed

    await pilot_nb.click(app.cells[0].expand_button)
    await pilot_nb.pause()
    assert not app.cells[0].collapsed

    await pilot_nb.click(app.cells[0].scroll_button, times=2)
    await pilot_nb.pause()
    assert app.cells[0].collapsed


async def test_run_cell(pilot, mocker):
    app: netbook.JupyterTextualApp = pilot.app
    await pilot.pause()
    poller = mocker.patch("zmq.asyncio.Poller")
    poller.return_value.poll = mocker.AsyncMock(return_value={app.kernel_client.iopub_channel.socket: 1})
    app.kernel_client.execute.return_value = "id1"

    # Test normal execution
    app.kernel_client.iopub_channel.get_msg = mocker.AsyncMock(
        side_effect=[
            {
                "parent_header": {"msg_id": "id1"},
                "header": {"msg_type": "stream"},
                "content": {"name": "stdout", "text": "  \nout\n  "},
            },
            {
                "parent_header": {"msg_id": "id1"},
                "header": {"msg_type": "stream"},
                "content": {"name": "stdout", "text": "outout"},
            },
            {
                "parent_header": {"msg_id": "id1"},
                "header": {"msg_type": "display_data"},
                "content": {"data": {"text/plain": "data"}, "metadata": {}},
            },
            {
                "parent_header": {"msg_id": "id1"},
                "header": {"msg_type": "execute_result"},
                "content": {"execution_count": 1, "data": {"text/plain": "data"}, "metadata": {}},
            },
            {
                "parent_header": {"msg_id": "id2"},  # Wrong id
            },
            {
                "parent_header": {"msg_id": "id1"},
                "header": {"msg_type": "status"},
                "content": {"execution_state": "idle"},
            },
        ]
    )
    app.kernel_client._recv_reply = mocker.AsyncMock(
        return_value={
            "parent_header": {"msg_id": "id1"},
            "header": {"msg_type": "execute_reply"},
            "content": {
                "status": "ok",
                "payload": [{"source": "page", "data": {"text/plain": "payload"}}],
                "execution_count": 1,
            },
        }
    )

    app.cells[0].source.text = "some code"
    app.action_run_cells("selection")
    tasks = list(pilot.app.kernel_access_queue)
    assert len(tasks) == 1
    await asyncio.gather(*pilot.app.kernel_access_queue, return_exceptions=True)
    assert tasks[0].result() is None
    await pilot.pause()
    assert len(app.cells[0].all_outputs) == 4
    assert app.cells[0].all_outputs[0].text == "  \nout\n  outout"

    # edit the cell
    app.cells[0].source.text = "new code"
    await pilot.pause()
    assert "∙" in app.cells[0].counter_format

    # Add a new cell
    await app.action_insert_cell_below()
    await pilot.pause()
    assert len(app.cells) == 2
    assert app.focused_cell_id == 1

    # Test error on execution
    app.cells[1].source.text = "some other code"
    app.kernel_client.execute.return_value = "id1"
    app.kernel_client.iopub_channel.get_msg = mocker.AsyncMock(
        side_effect=[
            {
                "parent_header": {"msg_id": "id1"},
                "header": {"msg_type": "error"},
                "content": {"ename": "RuntimeError", "evalue": "3", "traceback": "traceback"},
            },
            {
                "parent_header": {"msg_id": "id1"},
                "header": {"msg_type": "status"},
                "content": {"execution_state": "idle"},
            },
        ]
    )
    app.kernel_client._recv_reply = mocker.AsyncMock(
        return_value={
            "parent_header": {"msg_id": "id1"},
            "header": {"msg_type": "execute_reply"},
            "content": {"status": "error", "execution_count": 1, "payload": [], "ename": "RuntimeError"},
        }
    )

    app.action_extend_selection_above()
    await pilot.pause()
    app.action_run_cells("selection")
    tasks = list(pilot.app.kernel_access_queue)
    assert len(tasks) == 2
    await asyncio.gather(*pilot.app.kernel_access_queue, return_exceptions=True)
    assert tasks[0].cancelled() or tasks[0].exception()
    assert tasks[1].cancelled() or tasks[1].exception()
    await pilot.pause()
    assert app.cells[0].execution_count == 1
    assert app.cells[1].execution_count == " "

    # Test kernel timeout
    poller.return_value.poll = mocker.AsyncMock(side_effect=[{}, {app.kernel_client.iopub_channel.socket: 1}])
    app.kernel_manager.is_alive = mocker.Mock(side_effect=[True, False])

    app.action_select_all_cells()
    app.action_run_cells("selection")
    app.action_select_all_cells()
    app.action_run_cells("selection")  # Run them two times
    tasks = list(pilot.app.kernel_access_queue)
    assert len(tasks) == 4
    await asyncio.gather(*pilot.app.kernel_access_queue, return_exceptions=True)
    for task in tasks:
        assert task.cancelled() or task.exception()
    await pilot.pause()
    assert app.cells[0].execution_count == " "
    assert app.cells[1].execution_count == " "
