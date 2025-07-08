%load_ext rich

# Set the number of columns for tqdm. A bit arbitrary but works better than the default.
from os import environ as _environ
_environ['TQDM_NCOLS'] = '80'

from pandas import DataFrame as _DataFrame
from pandas import set_option as _set_option

_set_option("display.expand_frame_repr", True)

def _pd_rich_repr(self, console, console_options):
    from rich.table import Table
    from rich.box import SIMPLE

    from pandas._config.config import get_option
    from pandas.io.formats.format import DataFrameFormatter
    from pandas.io.formats.string import StringFormatter

    formatter = DataFrameFormatter(
        self,
        max_rows=get_option("display.max_rows"),
        max_cols=get_option("display.max_columns"),
        min_rows=get_option("display.min_rows"),
        show_dimensions=get_option("display.show_dimension"),
    )
    sformatter = StringFormatter(formatter)
    string_cols = sformatter._get_strcols()

    table = Table(box=SIMPLE, row_styles=["dim", ""])
    if formatter.has_index_names:
        for i, c in enumerate(string_cols):
            table.add_column("\n".join(c[:2]), style="bold" if i == 0 else None, justify="left" if i == 0 else "right")
        start_row = 2
    else:
        for i, c in enumerate(string_cols):
            table.add_column(c[0], style="bold" if i == 0 else None, justify="left" if i == 0 else "right")
        start_row = 1
    for i in range(start_row, len(string_cols[0])):
        table.add_row(*[c[i] for c in string_cols])
    if get_option("display.expand_frame_repr"):
        console_options = console_options.update(max_width=256)
    yield from table.__rich_console__(console, console_options)
    if formatter.should_show_dimensions:
        yield formatter.dimensions_info.strip()


_DataFrame.__rich_console__ = _pd_rich_repr
