import os
import sys
import typing as t
from traceback import format_exception_only
from traceback import format_tb
from urllib import parse

import click

from mons.baseUtils import *
from mons.config import Env
from mons.config import get_default_install
from mons.config import UserInfo
from mons.errors import TTYError
from mons.formatting import colorize
from mons.formatting import TERM_COLORS
from mons.install import Install as T_Install


def confirm_ext(*params, default, dangerous: bool = False, **attrs):
    """Extension to :func:`click.confirm`.

    Throws a :class:`TTYError` if `stdin` is not a TTY,
    and returns `True` if :attr:`Env.ignore_errors` is set.

    :param dangerous: if set to `False` (default), :attr:`Env.skip_confirmation`
    will also be checked.
    """

    ctx = click.get_current_context(silent=True)
    env = ctx and ctx.find_object(Env)

    if env:
        if env.ignore_errors:
            return True
        elif env.skip_confirmation and not dangerous:
            return True

    if not os.isatty(sys.stdin.fileno()):
        if dangerous:
            msg = "Use '--force' to skip error prompts."
        else:
            msg = "Use '--yes' to skip confirmation prompts."
        raise TTYError("not a tty.\n" + msg)

    return click.confirm(default=default, *params, **attrs)


def env_flag_option(
    var: str, *param_decls: str, help="", process_value: t.Any = None, **kwargs: t.Any
):
    def callback(ctx: click.Context, param: click.Parameter, value: bool):
        env = ctx.find_object(Env)
        if process_value:
            value = process_value(ctx, param, value)
        setattr(env, var, value)

    kwargs.setdefault("expose_value", False)
    kwargs.setdefault("is_eager", True)
    kwargs.setdefault("help", help)
    kwargs["callback"] = callback
    return click.option(*param_decls, **kwargs)


def yes_option(*param_decls: str, **kwargs: t.Any):
    if not param_decls:
        param_decls = ("--yes",)

    kwargs.setdefault("is_flag", True)
    return env_flag_option(
        "skip_confirmation", *param_decls, help="Skip confirmation prompts.", **kwargs
    )


def force_option(*param_decls: str, **kwargs: t.Any):
    if not param_decls:
        param_decls = ("--force",)

    kwargs.setdefault("is_flag", True)
    return env_flag_option(
        "ignore_errors",
        *param_decls,
        help="Ignore errors and confirmation prompts.",
        **kwargs,
    )


class CatchErrorsGroup(click.Group):
    def main(self, args=None, *params, **extra):
        def pop_arg(arg):
            if arg in sys.argv:
                if not args:
                    sys.argv.remove(arg)
                return True
            return False

        debug = pop_arg("--debug")
        wait = pop_arg("--wait")
        if pop_arg("--prompt-install"):
            os.environ["MONS_PROMPT_INSTALL"] = "1"
        try:
            super().main(args=args, *params, **extra)
        except SystemExit as e:
            if wait:
                click.pause()
            raise e
        except Exception as e:
            if debug or os.environ.get("MONS_DEBUG", "false") == "true":
                click.echo(
                    colorize("An unhandled exception has occurred.", TERM_COLORS.ERROR)
                )
                click.echo("".join(format_tb(e.__traceback__)), nl=False)
                click.echo(
                    colorize(
                        "".join(format_exception_only(type(e), e)), TERM_COLORS.ERROR
                    ),
                    nl=False,
                )
            else:
                click.echo(colorize(repr(e), TERM_COLORS.ERROR))
                click.echo(
                    f"""An unhandled exception has occurred.
Use the --debug flag to disable clean exception handling."""
                )


def color_option(*param_decls: str, **kwargs: t.Any):
    def auto_color():
        if os.environ.get("NO_COLOR"):
            return False
        # TODO: Special cases for pagers not covered by click

        # Default to whatever click decides
        return None

    def callback(ctx, param, value: t.Optional[str]):
        if value is None:
            return auto_color()

        if value == "always":
            return True
        if value == "never":
            return False
        if value == "auto":
            return None
        raise click.BadParameter("Possible values: auto, never, always", ctx, param)

    if not param_decls:
        param_decls = ("--color",)

    kwargs.setdefault("is_eager", True)
    kwargs.setdefault("help", "Specify when to use colored output: auto, always, none")
    kwargs.setdefault("metavar", "WHEN")
    kwargs["callback"] = callback
    return click.option(*param_decls, **kwargs)


class Install(click.ParamType):
    name = "Install"

    def __init__(self, exist=True, resolve_install=False, check_path=True) -> None:
        super().__init__()
        self.exist = exist
        self.resolve_install = resolve_install
        self.validate_path = check_path

    def convert(self, value: t.Union[str, T_Install], param, ctx):
        userinfo = ctx and ctx.find_object(UserInfo)
        if not userinfo:
            return value
        installs = userinfo.installs

        if self.exist:
            if not isinstance(value, T_Install):
                try:
                    Install.validate_install(
                        value, validate_path=self.validate_path, ctx=ctx
                    )
                except ValueError as err:
                    self.fail(str(err), param, ctx)
                except FileNotFoundError as err:
                    raise click.UsageError(str(err), ctx)

                if self.resolve_install:
                    value = installs[value]
        else:
            if value in installs:
                self.fail(f"Install {value} already exists.", param, ctx)

        return value

    @classmethod
    def validate_install(cls, install: str, validate_path=True, ctx=None):
        userinfo: UserInfo = (ctx or click.get_current_context()).obj
        installs = userinfo.installs

        if install not in installs:
            raise ValueError(f"Install {install} does not exist")

        path = installs[install].path
        if validate_path:
            error = None
            if not os.path.exists(path):
                error = "does not exist."
            elif not os.path.basename(path) == "Celeste.exe":
                error = "does not point to Celeste.exe"

            if error:
                raise FileNotFoundError(
                    f"""Install {install} does not have a valid path:
{TERM_COLORS.ERROR}{path} {error}{TERM_COLORS.RESET}
Use `set-path` to assign a new path."""
                )


def install(*param_decls, resolve=True, **attrs):
    """Alias for a `click.argument` of type `Install` that will use the default provided by `MONS_DEFAULT_INSTALL`

    Requires a command `cls` of `CommandExt`."""
    return click.argument(
        *param_decls,
        type=Install(resolve_install=resolve),
        cls=OptionalArg,
        default=get_default_install,
        prompt="Install name",
        warning="mons default install set to {default}",
        prompt_envvar="MONS_PROMPT_INSTALL",
        **attrs,
    )


class URL(click.ParamType):
    name = "URL"

    def __init__(
        self,
        default_scheme: t.Optional[str] = None,
        valid_schemes: t.Optional[t.Collection[str]] = None,
        require_path=False,
    ) -> None:
        super().__init__()
        self.default_scheme = default_scheme
        self.valid_schemes = valid_schemes
        self.require_path = require_path

    def convert(self, value: t.Union[str, parse.ParseResult], param, ctx):
        if isinstance(value, parse.ParseResult):
            return value

        try:
            parsed_url = parse.urlparse(value)

            if self.require_path and not parsed_url.path:
                self.fail("Path component required for URL.", param, ctx)
            if not parsed_url.scheme and self.default_scheme:
                if not value.startswith("//"):
                    # urlparse treats urls NOT starting with // as relative URLs
                    # https://docs.python.org/3.10/library/urllib.parse.html?highlight=urlparse#urllib.parse.urlparse
                    parsed_url = parse.urlparse(
                        "//" + value, scheme=self.default_scheme
                    )
                else:
                    parsed_url._replace(scheme=self.default_scheme)
            if self.valid_schemes and parsed_url.scheme not in self.valid_schemes:
                self.fail(f"URI scheme '{parsed_url.scheme}' not allowed.", param, ctx)

            return parsed_url
        except ValueError:
            self.fail(f"{value} is not a valid URL.", param, ctx)


class DefaultOption(click.Option):
    """Mark this option as being a _default option"""

    register_default = True

    def __init__(self, param_decls: t.Sequence[str], **attrs):
        param_decls = [decl + "_default" for decl in param_decls]
        super(DefaultOption, self).__init__(param_decls, **attrs)
        self.hidden = True


class ExplicitOption(click.Option):
    """Fix the help string for this option to display as an optional argument"""

    def get_help_record(self, ctx):
        help = super(ExplicitOption, self).get_help_record(ctx)
        if help:
            return (help[0].replace(" ", "[=", 1) + "]",) + help[1:]

    def sphinx_get_help_record(
        self, help_func: t.Callable[[click.Parameter], t.Tuple[str]]
    ):
        help = help_func(self)
        return (help[0].replace(" ", "[=", 1) + "]",) + help[1:]


class PlaceHolder(click.Argument):
    """Mark this argument as a placeholder that isn't processed"""

    register_placeholder = True


class OptionalArg(click.Argument):
    def __init__(
        self,
        param_decls: t.Sequence[str],
        **attrs,
    ) -> None:
        self.warning: t.Optional[str] = attrs.pop("warning", None)
        self.prompt: str = attrs.pop("prompt", "")
        self.prompt_envvar: str = attrs.pop("prompt_envvar", "")
        super().__init__(param_decls, True, **attrs)

    def should_prompt(self, ctx: click.Context):
        return os.environ.get(self.prompt_envvar, None) and not ctx.resilient_parsing

    def add_to_parser(self, parser: click.parser.OptionParser, ctx: click.Context):
        if not self.should_prompt(ctx):
            return super().add_to_parser(parser, ctx)

    def consume_value(self, ctx: click.Context, opts: t.Mapping[str, t.Any]):
        if self.should_prompt(ctx):
            source = click.core.ParameterSource.PROMPT
            default = self.get_default(ctx)
            value = click.prompt(
                self.prompt,
                default=default,
                type=self.type,
                value_proc=lambda x: self.process_value(ctx, x),
            )
            return value, source

        return super().consume_value(ctx, opts)


class CommandExt(click.Command):
    """Command implementation for extended option and argument types"""

    warnings: t.List[str] = list()

    def make_parser(self, ctx):
        """Strip placeholder params"""
        self.params = [
            a for a in self.params if not getattr(a, "register_placeholder", None)
        ]
        return super().make_parser(ctx)

    def parse_args(self, ctx, args):
        # Handle any OptionalArgs as needed
        def handle_optionalarg(o):
            if isinstance(o, OptionalArg) and o.default:
                default = (
                    o.default() if isinstance(o.default, t.Callable) else o.default
                )
                if default:
                    assert o.name
                    # set value for param directly in the context
                    ctx.params.update({o.name: o.type_cast_value(ctx, default)})
                    if o.warning:
                        self.warnings.append(o.warning.format(default=default))

                    # ensure that the command is invoked even if there are technically no arguments passed
                    self.no_args_is_help = False
                    return True
            return False

        ctx.command.params = [
            o for o in ctx.command.params if not handle_optionalarg(o)
        ]

        # Translate any opt to opt_default as needed
        options = [
            o for o in ctx.command.params if getattr(o, "register_default", None)
        ]
        prefixes = {
            p.replace("_default", "")
            for p in sum((o.opts for o in options), [])
            if p.startswith("--")
        }
        for i, a in enumerate(args):
            a = a.split("=", 1)
            if a[0] in prefixes and len(a) == 1:
                args[i] = a[0] + "_default"

        return super(CommandExt, self).parse_args(ctx, args)

    def invoke(self, ctx):
        """Emit additional warnings as needed"""
        for w in self.warnings:
            click.echo(colorize(w, TERM_COLORS.WARNING))
        return super().invoke(ctx)
