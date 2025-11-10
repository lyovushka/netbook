import netbook
import textual.pilot
import pytest_mock
import nbformat


async def test_actions(pilot: textual.pilot.Pilot, mocker: pytest_mock.MockerFixture):
    app: netbook.JupyterTextualApp = pilot.app

    # Test split cell
    assert len(app.cells) == 1
    assert app.cells[0].has_class("input_focused")
    await pilot.press("a", "enter", "enter", "b", "up", "ctrl+shift+minus")
    await pilot.pause()
    assert len(app.cells) == 2
    assert app.cells[0].source.text == "a"
    assert app.cells[1].source.text == "b"
    assert app.cells[1].has_class("input_focused")

    # Test run cell
    await pilot.press("up")
    await pilot.pause()
    execute_mock = mocker.Mock()
    mocker.patch("netbook._cell.CodeCell.execute", execute_mock)
    await pilot.press("shift+enter")
    await pilot.pause()
    execute_mock.assert_called_once()
    assert len(app.cells) == 2
    assert app.cells[1].has_class("focused")
    assert not app.cells[1].has_class("input_focused")

    # Test up/down
    await pilot.press("up")
    await pilot.pause()
    assert app.cells[0].has_class("focused")
    await pilot.press("down")
    await pilot.pause()
    assert app.cells[1].has_class("focused")
    await pilot.press("shift+up")
    await pilot.pause()
    assert app.cells[0].has_class("focused")
    assert app.cells[0].has_class("multiselect")
    await pilot.press("shift+down")
    assert app.cells[1].has_class("focused")
    assert not app.cells[1].has_class("multiselect")

    # Test move up/down
    await pilot.press("ctrl+shift+up")
    await pilot.pause()
    assert app.cells[0].has_class("focused")
    assert app.cells[0].source.text == "b"
    assert app.cells[1].source.text == "a"
    await pilot.press("ctrl+shift+down")
    await pilot.pause()
    assert app.cells[0].source.text == "a"
    assert app.cells[1].source.text == "b"

    # Insert cells
    assert app.cells[1].has_class("focused")
    assert not app.cells[1].has_class("input_focused")
    await pilot.press("a")
    await pilot.pause()
    assert len(app.cells) == 3
    assert app.cells[2].source.text == "b"
    assert app.cells[1].has_class("focused")
    assert not app.cells[1].has_class("input_focused")
    await pilot.press("b")
    await pilot.pause()
    assert len(app.cells) == 4
    assert app.cells[2].has_class("focused")

    # Merge cells
    await pilot.press("M", "M")
    await pilot.pause()
    assert len(app.cells) == 3
    assert app.cells[2].source.text == "\n\nb"
    assert app.cells[2].has_class("focused")

    # Add a cell at the end
    await app.action_insert_cell_at_end()
    await pilot.pause()
    assert len(app.cells) == 4
    assert app.cells[3].has_class("focused")


async def test_copy_paste(pilot: textual.pilot.Pilot):
    app: netbook.JupyterTextualApp = pilot.app
    await pilot.press("a", "s", "d", "f", "escape")
    await pilot.pause()
    assert len(app.cells) == 1
    assert app.cells[0].source.text == "asdf"

    # Test cut
    await pilot.press("x")
    await pilot.pause()
    # should insert a new empty cell
    assert len(app.cells) == 1
    assert app.cells[0].source.text == ""

    # Test paste
    await pilot.press("v")
    await pilot.pause()
    assert len(app.cells) == 2
    assert app.cells[1].source.text == "asdf"
    assert app.cells[1].has_class("focused")

    # Test copy and paste above
    await pilot.press("up", "c", "V")
    await pilot.pause()
    assert len(app.cells) == 3
    assert app.cells[0].has_class("focused")
    assert app.cells[0].source.text == ""

    # Test delete
    await pilot.press(f"{app.CMDTRL}+a", "d", "d")
    await pilot.pause()
    # should insert a new empty cell
    assert len(app.cells) == 1
    assert app.cells[0].source.text == ""

    # Test undo deletion
    await pilot.press("z")
    await pilot.pause()
    assert len(app.cells) == 4
    assert app.cells[0].source.text == ""
    assert app.cells[1].source.text == ""
    assert app.cells[2].source.text == "asdf"
    assert app.cells[3].source.text == ""

    # One more undo
    await pilot.press("z")
    await pilot.pause()
    assert len(app.cells) == 5
    assert app.cells[0].source.text == "asdf"


async def test_toggle_actions(pilot: textual.pilot.Pilot):
    app: netbook.JupyterTextualApp = pilot.app

    # Go into command mode
    await pilot.press("escape")
    await pilot.pause()
    assert app.cells[0].source.show_line_numbers

    # Toggle line numbers
    await pilot.press("l")
    await pilot.pause()
    assert not app.cells[0].source.show_line_numbers

    # Add a new cell
    await pilot.press("b")
    await pilot.pause()
    assert app.cells[1].source.show_line_numbers

    # Toggle all line numbers
    await pilot.press("L")
    await pilot.pause()
    assert not app.cells[0].source.show_line_numbers
    assert not app.cells[1].source.show_line_numbers
    await pilot.press("L")
    await pilot.pause()
    assert app.cells[0].source.show_line_numbers
    assert app.cells[1].source.show_line_numbers

    assert app.cells[1].has_class("focused")
    assert not app.cells[1].collapsed
    assert not app.cells[1].scrolled

    # Toggle output
    await pilot.press("o")
    await pilot.pause()
    assert app.cells[1].collapsed
    assert not app.cells[1].scrolled

    # Toggle output scrolling
    await pilot.press("O")
    await pilot.pause()
    assert app.cells[1].scrolled

    # Toggle help
    assert not app.screen.query("HelpPanel")
    await pilot.press("h")
    await pilot.pause()
    assert app.screen.query("HelpPanel")
    await pilot.press("h")
    await pilot.pause()
    assert not app.screen.query("HelpPanel")


async def test_kernel_actions(pilot: textual.pilot.Pilot, mocker: pytest_mock.MockerFixture):
    app: netbook.JupyterTextualApp = pilot.app
    assert app.cells[0].has_class("input_focused")
    await pilot.press("a", "s", "df", "escape")
    await pilot.pause()

    # Interrupt kernel
    await pilot.press("i", "i")
    await pilot.pause()
    app.kernel_manager.interrupt_kernel.assert_called_once()

    # Restart kernel
    await pilot.press("0", "0")
    await pilot.pause()
    app.kernel_manager.restart_kernel.assert_called_once()

    # Restart and run all cells
    mock_execute = mocker.Mock()
    mocker.patch("netbook._cell.CodeCell.execute", mock_execute)
    app.action_restart_and_run_all()
    assert app.kernel_manager.restart_kernel.call_count == 2
    mock_execute.assert_called_once()


async def test_load_language(mocker: pytest_mock.MockerFixture):
    # Test loading lanugage with available tree sitter package
    nb = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell()])
    km = mocker.Mock()
    km.kernel_spec.language = "julia"
    kc = mocker.Mock()
    kc.execute_interactive = mocker.AsyncMock()
    app = netbook.JupyterTextualApp(km, kc, "", nb, image_class=None)
    assert app.tree_sitter_language is not None
    assert app.language_highlights_query != ""
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.cells[0].source.language == "julia"

    # Test when we can't load the language
    km.kernel_spec.language = "R"
    mocker.patch("netbook._textual_app.JupyterTextualApp.notify")
    app = netbook.JupyterTextualApp(km, kc, "", nb, image_class=None)
    app.notify.assert_called_once_with(
        "Syntax highlighting is not available for R. Try installing the package `tree_sitter_r`"
    )
