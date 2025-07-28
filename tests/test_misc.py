import textual.pilot
import netbook
import pytest_mock


async def test_smoke(pilot: textual.pilot.Pilot):
    await pilot.exit(0)
    pilot.app.kernel_client.shutdown.assert_called_once()


async def test_command_palette(pilot_nb: textual.pilot.Pilot):
    app: netbook.JupyterTextualApp = pilot_nb.app
    await pilot_nb.press("escape", "p")
    await pilot_nb.pause()
    await pilot_nb.press(*list("clear all"), "enter")
    await pilot_nb.pause()
    for cell in app.cells:
        if isinstance(cell, netbook._cell.CodeCell):
            assert cell.all_outputs == []


async def test_save(pilot_nb: textual.pilot.Pilot, mocker: pytest_mock.MockerFixture):
    mock_write = mocker.patch("nbformat.write")
    pilot_nb.app: netbook.JupyterTextualApp
    pilot_nb.app.action_save_notebook()
    mock_write.assert_called_once()
    assert mock_write.call_args.args[1] == "./tests/test.ipynb"
    nb = mock_write.call_args.args[0]
    assert len(nb.cells) == 7
    assert tuple(cell.cell_type for cell in nb.cells) == ("code",) * 4 + ("markdown", "raw") + ("code",)


async def test_quit(pilot: textual.pilot.Pilot, mocker: pytest_mock.MockerFixture):
    app: netbook.JupyterTextualApp = pilot.app
    app.cells[0].source.text = "asdf"
    await pilot.pause()
    assert app.unsaved
    mock_notify = mocker.Mock()
    mock_exit = mocker.Mock()
    app.notify = mock_notify
    app.exit = mock_exit
    await pilot.press("escape", "ctrl+q")
    await pilot.pause()
    mock_notify.assert_called_once()
    mock_exit.assert_not_called()
    await pilot.press("ctrl+q", "ctrl+q")
    await pilot.pause()
    mock_exit.assert_called()


def test_cmdline(mocker: pytest_mock.MockerFixture):
    nb = netbook.JupyterNetbook()
    nb.initialize(["--generate-config"])
    assert not hasattr(nb, "textual_app")
    nb = netbook.JupyterNetbook()
    nb.initialize([])
    assert nb.textual_app.nbfile.startswith("Untitled")
    nb = netbook.JupyterNetbook()
    nb.initialize(["./tests/test.ipynb"])
    assert nb.textual_app.nbfile == "./tests/test.ipynb"


async def test__get_range_cells(pilot: textual.pilot.Pilot):
    app: netbook.JupyterTextualApp = pilot.app

    # Add another cell
    await pilot.press("shift+enter")
    await pilot.pause()
    assert len(app.cells) == 2
    assert app.focused_cell_id == 1
    assert app.cells == app._get_range_cells(app.Range.all)
    assert [app.cells[1]] == app._get_range_cells(app.Range.selection)
    assert app.cells[:1] == app._get_range_cells(app.Range.above)
    assert app.cells[1:] == app._get_range_cells(app.Range.below)
