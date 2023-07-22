import logging
import sys
import time
import traceback
import typing as t
from contextlib import contextmanager
from logging import LogRecord

import click
from tqdm import tqdm

logger = logging.getLogger(__name__)


T = t.TypeVar("T")

if t.TYPE_CHECKING:
    # Use type hints from `tqdm.__init__`...
    class ProgressBar(tqdm[T]):
        """Simple wrapper for `tqdm` to only enable for INFO or DEBUG logs"""

        pass

else:
    # ...but call a wrapper function at runtime
    def ProgressBar(*args, disable=None, **kwargs):
        # disable if logging isn't at least INFO
        kwargs["disable"] = kwargs.get(
            "disable", not logger.isEnabledFor(logging.INFO) or None
        )
        # always leave if DEBUG logging
        kwargs["leave"] = logger.isEnabledFor(logging.DEBUG) or kwargs.get(
            "leave", None
        )
        return tqdm(*args, **kwargs)


@contextmanager
def timed_progress(msg: str, loglevel: int = logging.INFO):
    """Times execution of the current context, then prints :param:`msg` with :func:`tqdm.write`.

    :param msg: Message to be printed. Formatted with a `time` kwarg."""
    start = time.perf_counter()
    yield
    end = time.perf_counter()
    # Carriage return ensures msg is printed properly even after multiple progress bars
    logger.log(loglevel, "\r" + msg.format(time=end - start))


LOGLEVEL_STYLE = {
    logging.CRITICAL: {"fg": "red", "bold": True},
    logging.ERROR: {"fg": "red"},
    logging.WARNING: {"fg": "yellow"},
    logging.INFO: {},
    logging.DEBUG: {"fg": "blue", "italic": True},
}


class ClickFormatter(logging.Formatter):
    def formatMessage(self, record: LogRecord) -> str:
        style: t.Dict[str, t.Any] = LOGLEVEL_STYLE.get(record.levelno, {})
        # log all level names regardless in debug mode
        if not style and logger.isEnabledFor(logging.DEBUG):
            style = {"italic": True}

        msg = record.getMessage()
        if style:
            prefix = click.style(record.levelname.lower() + ": ", **style)
            msg = "\n".join(prefix + line for line in msg.splitlines())
        return msg

    def formatException(self, ei) -> str:
        e_type, e, ei_tb = ei
        tb = "".join(traceback.format_tb(ei_tb))
        msg = "".join(traceback.format_exception_only(e_type, e))
        if msg[-1:] == "\n":
            msg = msg[:-1]
        return tb + click.style(msg, fg="red")


class EchoHandler(logging.Handler):
    def emit(self, record: LogRecord) -> None:
        try:
            with tqdm.external_write_mode(sys.stderr):
                msg = self.format(record)
                click.echo(msg, err=True)
        except Exception:
            self.handleError(record)
