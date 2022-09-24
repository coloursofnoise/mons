import typing as t

if t.TYPE_CHECKING:
    import click
import mons.clickExt as clickExt
from inspect import signature, unwrap


def unwrap_count(f):
    depth = 0

    def incr(_):
        nonlocal depth
        depth = depth + 1
        return False

    return unwrap(f, stop=incr), depth


def test_command_arguments(command: "click.Command"):
    assert command.callback

    callback, depth = unwrap_count(command.callback)

    callback_args = signature(callback).parameters.keys()
    callback_args_unique = set(callback_args)
    command_params = [
        param.name
        for param in command.params
        if param.expose_value and not isinstance(param, clickExt.PlaceHolder)
        if param.name
    ]

    for param in command_params:
        assert (
            param in callback_args
        ), f"Callback for '{command.name}' has missing argument: '{param}'"
        callback_args_unique.discard(param)

    assert depth == len(
        callback_args_unique
    ), f"Callback for '{command.name}' has too many positional arguments: '{callback_args_unique}"
