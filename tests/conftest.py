# A hack to make textual_image work in tests on windows
import unittest.mock

# Ensures textual_image.renderble.Image is set to UnicodeImage
with unittest.mock.patch("sys.__stdout__", None):
    import textual_image.renderable
import textual_image._terminal

# Hardcode the cell size - it throws on windows.
setattr(textual_image._terminal.get_cell_size, "_result", textual_image._terminal.CellSize(10, 20))

import textual_image.widget

import netbook

import nbformat
import pytest


@pytest.fixture
async def pilot(mocker):
    nb = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell()])
    km = mocker.Mock()
    km.kernel_spec.language = "python"
    kc = mocker.Mock()
    kc.execute_interactive = mocker.AsyncMock()
    app = netbook.JupyterTextualApp(km, kc, "", nb, image_class=textual_image.widget.HalfcellImage)
    async with app.run_test() as pilot:
        await pilot.pause()
        yield pilot


@pytest.fixture
async def pilot_nb(mocker):
    nbfile = "./tests/test.ipynb"
    nb = nbformat.read(nbfile, nbformat.current_nbformat)
    km = mocker.Mock()
    km.kernel_name = nb.metadata.kernelspec.name
    km.kernel_spec.language = nb.metadata.kernelspec.language
    km.kernel_spec.display_name = nb.metadata.kernelspec.display_name
    kc = mocker.Mock()
    kc.execute_interactive = mocker.AsyncMock()
    app = netbook.JupyterTextualApp(km, kc, nbfile, nb, image_class=textual_image.widget.HalfcellImage)
    async with app.run_test() as pilot:
        await pilot.pause()
        yield pilot
