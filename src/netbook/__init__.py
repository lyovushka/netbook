import pathlib
import sys

import jupyter_client.consoleapp
import jupyter_core.application
import jupyter_core.utils

import nbformat

import textual

import traitlets

from netbook._textual_app import JupyterTextualApp


class JupyterNetbook(jupyter_core.application.JupyterApp, jupyter_client.consoleapp.JupyterConsoleApp):
    name = "jupyter-netbook"
    description = """
        A terminal-based app for jupyter notebooks.
    """
    flags = traitlets.Dict({**jupyter_core.application.base_flags, **jupyter_client.consoleapp.app_flags})
    aliases = traitlets.Dict({**jupyter_core.application.base_aliases, **jupyter_client.consoleapp.app_aliases})

    kernel_client_class = jupyter_client.asynchronous.AsyncKernelClient
    # kernel_manager_class = jupyter_client.manager.AsyncKernelManager

    log = textual.log

    def initialize(self, argv):
        if not hasattr(self.log, "exception"):
            # Jupyter requires self.log.exception
            self.log.exception = self.log.error

        if sys.platform == "win32":
            # see https://github.com/zeromq/pyzmq/issues/1423
            import asyncio

            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        jupyter_core.application.JupyterApp.initialize(self, argv)
        if self._dispatching:
            return

        nb = None
        nbkernel = None
        # Determine the notebook name and content
        if len(self.extra_args) > 0:
            # TODO: what if multiple filenames are passed
            nbfile = self.extra_args[0]
            if pathlib.Path(nbfile).exists():
                nb = nbformat.read(nbfile, nbformat.current_nbformat)
                if "kernelspec" in nb.metadata:
                    nbkernel = nb.metadata.kernelspec.name
        else:
            # Determine a name like "Untitled{x}.ipynb"
            suffix = ""
            while pathlib.Path(f"Untitled{suffix}.ipynb").exists():
                suffix = suffix + 1 if suffix else 1
            nbfile = f"Untitled{suffix}.ipynb"

        if nbkernel and (
            "JupyterNetbook" not in self.cli_config or "kernel_name" not in self.cli_config["JupyterNetbook"]
        ):
            # If kernel_name is not explicitly specify but is present in the notebook, use that one
            self.kernel_name = nbkernel

        jupyter_client.consoleapp.JupyterConsoleApp.initialize(self, argv)

        # TODO: if --existing is specified, then self.kernel_manager is None.
        self.textual_app = JupyterTextualApp(self.kernel_manager, self.kernel_client, nbfile, nb)

    def start(self):
        jupyter_core.application.JupyterApp.start(self)
        self.textual_app.run()


def main(argv=None, **kwargs) -> None:
    JupyterNetbook.launch_instance(argv, **kwargs)
