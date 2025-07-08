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
    app = netbook.JupyterTextualApp(km, kc, "", nb)
    async with app.run_test() as pilot:
        await pilot.pause()
        yield pilot


@pytest.fixture
async def pilot_nb():
    nb_app = netbook.JupyterNetbook()
    nb_app.initialize(["./tests/test.ipynb"])
    assert hasattr(nb_app, "textual_app")
    app = nb_app.textual_app
    async with app.run_test() as pilot:
        await pilot.pause()
        yield pilot
