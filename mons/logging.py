import logging
import traceback
import typing as t
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
        kwargs["disable"] = kwargs.get(
            "disable", not logger.isEnabledFor(logging.INFO) or None
        )
        kwargs["leave"] = kwargs.get("leave", None) and (
            not logger.isEnabledFor(logging.DEBUG)
        )
        return tqdm(*args, **kwargs)


LOGLEVEL_STYLE = {
    logging.CRITICAL: {"fg": "red", "bold": True},
    logging.ERROR: {"fg": "red"},
    logging.WARNING: {"fg": "yellow"},
    logging.INFO: {},
    logging.DEBUG: {"fg": "blue", "italic": True},
}


class ClickFormatter(logging.Formatter):
    def formatMessage(self, record: LogRecord) -> str:
        style = LOGLEVEL_STYLE.get(record.levelno, {})
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
            with tqdm.external_write_mode():
                msg = self.format(record)
                click.echo(msg, err=True)
        except Exception:
            self.handleError(record)
