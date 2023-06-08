import logging
from logging import LogRecord

import click


logger = logging.getLogger(__name__)


LOGLEVEL_STYLE = {
    logging.CRITICAL: {"fg": "red", "bold": True},
    logging.ERROR: {"fg": "red"},
    logging.WARNING: {"fg": "yellow"},
    logging.INFO: {},
    logging.DEBUG: {"fg": "blue", "italic": True},
}


class ClickFormatter(logging.Formatter):
    def format(self, record: LogRecord) -> str:
        style = LOGLEVEL_STYLE.get(record.levelno, {})
        # log all level names regardless in debug mode
        if not style and logger.isEnabledFor(logging.DEBUG):
            style = {"italic": True}

        msg = record.getMessage()
        if style:
            prefix = click.style(record.levelname.lower() + ": ", **style)
            msg = "\n".join(prefix + line for line in msg.splitlines())
        return msg


class EchoHandler(logging.Handler):
    def emit(self, record: LogRecord) -> None:
        try:
            click.echo(self.format(record), err=True)
        except Exception:
            self.handleError(record)
