import click

class EmptyFileError(Exception):
    pass

class TTYError(click.ClickException):
    def __init__(self, message: str) -> None:
        super().__init__(message)