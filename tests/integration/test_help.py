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
