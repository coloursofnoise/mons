from urllib.parse import urlparse

import click
import pytest

import mons.clickExt as clickExt


def color_cmd():
    @click.command()
    @clickExt.color_option()
    def cmd(color):
        return color

    return cmd


@pytest.mark.parametrize(
    ("color_arg", "output"),
    [
        ("auto", None),
        ("always", True),
        ("never", False),
    ],
)
def test_color_option(runner, color_arg, output):
    result = runner.invoke(color_cmd(), ["--color", color_arg], standalone_mode=False)
    assert result.exit_code == 0, result.output
    assert output == result.return_value


@pytest.mark.parametrize(("env", "output"), [({}, None), ({"NO_COLOR": "1"}, False)])
def test_color_option_auto(runner, env, output):
    result = runner.invoke(color_cmd(), env=env, standalone_mode=False)
    assert result.exit_code == 0, result.output
    assert output == result.return_value


def test_color_option_bad(runner):
    result = runner.invoke(color_cmd(), ["--color", "invalid"], standalone_mode=False)
    assert isinstance(result.exception, click.BadParameter)
    assert "Possible values: auto, never, always" in result.exception.message


@pytest.mark.parametrize(
    ("url_arg", "expect"),
    [
        ("https://mons.coloursofnoise.ca/file", "{url_arg}"),
        ("mons.coloursofnoise.ca/file", "file://{url_arg}"),
    ],
)
def test_url_type(runner, url_arg, expect):
    cmd = click.Command(
        "cmd",
        params=[click.Argument(["url"], type=clickExt.URL(default_scheme="file"))],
        callback=lambda url: url,
    )
    result = runner.invoke(cmd, [url_arg], standalone_mode=False)
    assert not result.exception, result.output
    assert result.return_value == urlparse(expect.format(url_arg=url_arg))


@pytest.mark.parametrize(
    ("param_args", "err"),
    [
        ({"valid_schemes": ["file"]}, "URI scheme 'https' not allowed"),
        ({"require_path": True}, "Path component required"),
    ],
)
def test_url_type_bad(runner, param_args, err):
    cmd = click.Command(
        "cmd", params=[click.Argument(["url"], type=clickExt.URL(**param_args))]
    )
    result = runner.invoke(cmd, ["https://mons.coloursofnoise.ca"])
    assert result.exception
    assert err in result.output


class TestCommandExt:
    @pytest.mark.parametrize(
        ("args", "expect"), [([], None), (["--opt"], True), (["--opt=value"], "value")]
    )
    def test_default_option(self, runner, args, expect):
        cmd = clickExt.CommandExt(
            "cmd",
            params=[
                clickExt.ExplicitOption(["--opt"]),
                clickExt.DefaultOption(["--opt"], is_flag=True),
            ],
            callback=lambda opt_default, opt: opt_default or opt,
        )

        result = runner.invoke(cmd, args, standalone_mode=False)
        assert result.return_value == expect

    def test_placeholder(self, runner):
        cmd = clickExt.CommandExt("cmd", params=[clickExt.PlaceHolder(["placeholder"])])

        result = runner.invoke(cmd, standalone_mode=False)
        assert not result.exception

    @pytest.mark.parametrize(
        ("default", "exception"),
        [
            (None, click.MissingParameter),
            (lambda: None, click.MissingParameter),
            ("A Value", None),
            (lambda: "A Value", None),
        ],
    )
    def test_optionalarg(self, runner, default, exception):
        cmd = clickExt.CommandExt(
            "cmd", params=[clickExt.OptionalArg(["arg"], default=default)]
        )

        result = runner.invoke(cmd, standalone_mode=False)
        assert exception is None or isinstance(result.exception, exception)
