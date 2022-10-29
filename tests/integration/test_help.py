import warnings

import click


def test_command_help(command: "click.Command"):
    if command.hidden:
        return

    assert command.help, f"Command '{command.name}' is missing help text"
    assert (
        command.get_short_help_str()
    ), f"Command '{command.name}' does is missing short help text"


def test_option_help(command: "click.Command"):
    if command.hidden:
        return

    for param in command.params:
        if isinstance(param, click.Option) and not param.hidden:
            assert (
                param.help
            ), f"Option '{param.name}' for command '{command.name}' is missing help text"


def test_no_args_is_help(command: "click.Command"):
    if command.hidden:
        return
    # Note: commands with only a clickExt.OptionalArg required do *not* fail this test. When an optional arg is applied 'no_args_is_help' is disabled.

    if command.no_args_is_help:
        assert any(
            param.required for param in command.params
        ), f"Command can be called with no arguments, but has 'no_args_is_help' enabled."
    elif any(param.required for param in command.params):
        warnings.warn(f"Command does not have 'no_args_is_help' enabled, but could.")
