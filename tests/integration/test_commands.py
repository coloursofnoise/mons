"""Sanity checks for click commands."""
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


def test_command_global_flags(command: "click.Command"):
    command_params = [
        param
        for param in command.params
        if param.expose_value
        and not isinstance(param, clickExt.PlaceHolder)
        and any(
            opt in clickExt.loglevel_flags
            for opt in (*param.opts, *param.secondary_opts)
        )
    ]

    assert (
        not command_params
    ), "Log level flags are swallowed by logger. Use `logger.isEnabledFor` to check logging level."

    command_params = [
        param
        for param in command.params
        if param.expose_value
        and not isinstance(param, clickExt.PlaceHolder)
        and any(
            opt in ["--pause", "--prompt-install"]
            for opt in (*param.opts, *param.secondary_opts)
        )
    ]

    assert (
        not command_params
    ), "The '--pause' and '--prompt-install' flags are swallowed by the command group."
