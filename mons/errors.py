import sys
import typing as t

import click

if sys.version_info < (3, 10):
    import typing_extensions as te
else:
    te = t


class EmptyFileError(Exception):
    pass


class TTYError(click.ClickException):
    def __init__(self, message: str) -> None:
        super().__init__("Could not read from stdin: " + message)


class ExceptionCount(Exception):
    def __init__(self, count: int):
        self.count = count
        super().__init__()


T = t.TypeVar("T")
P = te.ParamSpec("P")
R = t.TypeVar("R")


def silent_exec(
    func: t.Callable[P, t.Any], *params: P.args, **kwargs: P.kwargs
) -> None:
    """Execute `func`, ignoring any exceptions.

    :returns: `None`
    """
    try:
        func(*params, **kwargs)
    except Exception:
        pass


def try_exec(
    exception_type: t.Type[Exception], on_failure: t.Union[T, BaseException]
) -> t.Callable[[t.Callable[P, R]], t.Callable[P, t.Union[R, T]]]:
    def decorator(func: t.Callable[P, R]) -> t.Callable[P, t.Union[R, T]]:
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> t.Union[R, T]:
            try:
                return func(*args, **kwargs)
            except exception_type:
                if isinstance(on_failure, BaseException):
                    raise on_failure
                return on_failure

        return wrapper

    return decorator
