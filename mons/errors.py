import click
import typing as t


class EmptyFileError(Exception):
    pass


class TTYError(click.ClickException):
    def __init__(self, message: str) -> None:
        super().__init__("Could not read from stdin: " + message)


class MultiException(Exception):
    def __init__(self, message: str, list: t.List[Exception]):
        self.message = message
        self.list = list

    def __str__(self) -> str:
        return self.message + ":\n  " + "\n  ".join([str(e) for e in self.list])
