import click

class EmptyFileError(Exception):
    pass

class TTYError(click.ClickException):
    def __init__(self, message: str) -> None:
        super().__init__('Could not read from stdin: ' + message)