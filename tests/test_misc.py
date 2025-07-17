import textual.pilot
import netbook
import pytest_mock
import pytest


async def test_smoke(pilot: textual.pilot.Pilot):
    await pilot.exit(0)
    pilot.app.kernel_client.shutdown.assert_called_once()


async def test_save(pilot_nb: textual.pilot.Pilot, mocker: pytest_mock.MockerFixture):
    mock_write = mocker.patch("nbformat.write")
    pilot_nb.app.action_save()
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
