import logging
import os
import re
import shutil
import sys
import typing as t
from gettext import gettext as _
from io import UnsupportedOperation
from urllib import parse

import click

from mons import overlayfs
from mons.baseUtils import flatten_lines
from mons.baseUtils import partition
from mons.baseUtils import T
from mons.config import Env
from mons.config import get_default_install
from mons.config import UserInfo
from mons.errors import TTYError
from mons.formatting import format_rst_inline
from mons.install import Install as T_Install
from mons.utils import find_celeste_asm


logger = logging.getLogger(__name__)


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

    tty = True
    try:
        tty = sys.stdin.isatty()
    except UnsupportedOperation:
        tty = False

    if not tty:
        if dangerous:
            msg = "Use '--force' to skip error prompts."
        else:
            msg = "Use '--yes' to skip confirmation prompts."
        raise TTYError("not a tty.\n" + msg)

    return click.confirm(default=default, *params, **attrs)


def echo_via_pager(generator: t.Iterable[t.Any], color: t.Optional[bool] = None):
    """ "`click.echo_via_pager`, but using `less -F`."

    If it seems like the output will fit on a single screen,
    it is sent straight to stdout.
    """

    import codecs, itertools, math

    cols, rows = shutil.get_terminal_size()
    lines = []

    encoding = getattr(sys.stdout, "encoding", None) or sys.getdefaultencoding()
    try:
        if codecs.lookup(encoding).name == "ascii":
            encoding = "utf-8"
    except LookupError:
        pass

    iterator = flatten_lines(iter(generator))
    try:
        nlines = 0
        while True:
            text = next(iterator)
            lines.append(text)
            text = (
                click.termui.strip_ansi(  # pyright:ignore[reportPrivateImportUsage]
                    text
                )
                .rstrip("\n")
                .encode(encoding, "replace")
            )

            nlines += max(1, math.ceil(len(text) / cols))
            if nlines > rows:
                break
    except StopIteration:
        for line in lines:
            click.echo(line, nl=False, color=color)
        click.echo()  # end with newline
        return

    return click.echo_via_pager(itertools.chain(lines, iterator), color)


def prompt_selections(
    items: t.Sequence[t.Any],
    message="Selections",
    reverse=False,
    find_index: t.Optional[t.Callable[[str], t.Optional[int]]] = None,
):
    """Prompt the user to select items from a list.

    Heavily inspired by the `yay` (https://github.com/Jguer/yay) selection menu.

    :param items: List of items to display.
    :param message: Prompt message, defaults to "Selections"
    :param reverse: Display the list items in reverse.
    :param find_index: If provided, is called for each selection input by the user.
    Should return the `int` position of the matching item, or `None`.
    :return: A set of indexes corresponding to the selected items in the input list.
    """

    count = i = len(items)
    iterator = reversed if reverse else iter
    for item in iterator(items):
        click.echo(
            f"{click.style(i, fg='blue')} {click.style(str(item), bold=True)}", err=True
        )
        i -= 1

    prompt = click.style(">", fg="green")
    ans = str(
        click.prompt(
            prompt + " " + message,
            prompt_suffix=": (eg: 1 2 3, 1-3 or ^4)\n" + prompt,
            default="",
            show_default=False,
            err=True,
        )
    )

    # Check for exact match to answer first, ignoring quoting rules
    if find_index:
        idx = find_index(ans)
        if idx is not None:
            return {idx}

    # Split input, but allow quoting for multi-word literal selections
    args: t.List[str] = re.findall(r'\^?"[^"]+"|[^\s,]+', ans)

    selections: t.Set[int] = set()
    if args and args[0].startswith("^"):
        selections = set(range(1, count + 1))

    for arg in args:
        add, update = selections.add, selections.update
        if arg.startswith("^"):
            arg = arg[1:]
            add, update = selections.discard, selections.difference_update

        arg = arg.strip('"')

        if find_index:
            idx = find_index(arg)
            if idx is not None:
                add(idx + 1 if reverse else count - idx)
                continue

        if arg.isdigit() and 0 < int(arg) < count + 1:
            add(int(arg))
        elif len(arg.split("-")) == 2 and all(
            bound.isdigit() and 0 < int(bound) < count + 1 for bound in arg.split("-")
        ):
            start, stop = sorted(map(int, arg.split("-")))
            update(range(start, stop + 1))

    if not reverse:
        # Selection numbers are always displayed in descending order.
        # `count - sel` also takes care of subtracting 1 from each index.
        return {count - sel for sel in selections}

    return {sel - 1 for sel in selections}


class ParamTypeG(click.ParamType, t.Generic[T]):
    def convert(
        self,
        value: t.Union[str, T],
        param: t.Optional[click.Parameter],
        ctx: t.Optional[click.Context],
    ) -> T:
        return super().convert(value, param, ctx)


# clickExt generic overload
@t.overload
def type_cast_value(ctx: click.Context, type: ParamTypeG[T], value: t.Any) -> T:
    ...


# click overloads
@t.overload
def type_cast_value(ctx: click.Context, type: click.File, value: t.Any) -> t.IO[t.Any]:
    ...


@t.overload
def type_cast_value(ctx: click.Context, type: click.Path, value: t.Any) -> str:
    ...


# Base overload
@t.overload
def type_cast_value(ctx: click.Context, type: click.ParamType, value: t.Any) -> t.Any:
    ...


def type_cast_value(ctx, type, value):
    dummy = click.Option("-d", type=type)
    return dummy.type_cast_value(ctx, value)


def env_flag_option(
    var: str, *param_decls: str, help="", process_value: t.Any = None, **kwargs: t.Any
):
    def callback(ctx: click.Context, param: click.Parameter, value: bool):
        env = ctx.ensure_object(Env)
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


loglevel_flags = {
    "--debug": logging.DEBUG,
    "--quiet": logging.ERROR,
}


class CatchErrorsGroup(click.Group):
    def main(self, args=None, *params, **extra):
        # preserve sys.argv to ensure nested processes get the same input
        # FIXME (python 3.10): sys.orig_argv
        sys_argv = sys.argv

        def pop_arg(arg):
            if arg in sys_argv:
                if not args:
                    sys_argv.remove(arg)
                return True
            return False

        module_logger = logging.getLogger("mons")
        logflags, sys_argv = partition(lambda arg: arg in loglevel_flags, sys_argv)
        debug = "--debug" in logflags or os.getenv("MONS_DEBUG", "").lower() in (
            "true",
            "yes",
            "1",
        )
        if logflags:
            module_logger.setLevel(loglevel_flags[logflags[-1]])
        elif debug:
            module_logger.setLevel(logging.DEBUG)
        else:
            module_logger.setLevel(logging.INFO)

        pause = pop_arg("--pause")
        if pop_arg("--prompt-install"):
            os.environ["MONS_PROMPT_INSTALL"] = "1"
        try:
            super().main(args=args or sys_argv[1:], *params, **extra)
        except SystemExit as e:
            if pause:
                click.pause()
            sys.exit(e.code)
        except Exception as e:
            if debug:
                logger.exception("An unhandled exception has occurred:")
            else:
                logger.error(
                    "An unhandled exception has occurred:\n  "
                    + click.style(repr(e), "red")
                )
                logger.error(
                    "Use the --debug flag to disable clean exception handling."
                )
            sys.exit(1)


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
    kwargs.setdefault("help", "Specify when to use colored output: auto, always, none.")
    kwargs.setdefault("metavar", "WHEN")
    kwargs["callback"] = callback
    return click.option(*param_decls, **kwargs)


class Install(ParamTypeG[t.Union[str, T_Install]]):
    """Represents a Celeste install. Returns a path, or an `Install` object with `resolve_install`.

    :param exist: Install must already exist in the Installs config file.
    :param resolve_install: Return an `Install` object instead of a path.
    :param check_path: Ensures the path exists and is a valid Celeste install (includes a Celeste asm).
    :param require_everest: Requires the install to be patched with Everest.
    """

    name = "Install"

    def __init__(
        self, exist=True, resolve_install=False, check_path=True, require_everest=False
    ) -> None:
        if resolve_install and not exist:
            raise ValueError("'resolve_install' cannot be True when 'exist' is False.")
        super().__init__()
        self.exist = exist
        self.resolve_install = resolve_install
        self.validate_path = check_path
        self.require_everest = require_everest

    def convert(self, value: t.Union[str, T_Install], param, ctx):
        userinfo = ctx and ctx.find_object(UserInfo)
        if not (ctx and userinfo):
            return value
        installs = userinfo.installs

        if self.exist:
            if not isinstance(value, T_Install):
                try:
                    Install.validate_install(
                        ctx, value, validate_path=self.validate_path
                    )
                except ValueError as err:
                    self.fail(str(err), param, ctx)
                except FileNotFoundError as err:
                    raise click.ClickException(str(err))

                if self.require_everest:
                    installs[value].update_cache(read_exe=True)
                    if not installs[value].everest_version:
                        raise click.UsageError(
                            "Requires a modded Celeste install. Use `mons install` to install Everest first."
                        )

                if self.resolve_install:
                    value = installs[value]
        else:
            if value in installs:
                self.fail(f"Install {value} already exists.", param, ctx)

        return value

    @classmethod
    def validate_install(cls, ctx: click.Context, install: str, validate_path=True):
        userinfo = (ctx or click.get_current_context()).ensure_object(UserInfo)
        installs = userinfo.installs

        if install not in installs:
            raise ValueError(f"Install {install} does not exist.")

        if validate_path:
            path = installs[install].path
            if installs[install].overlay_base:
                overlayfs.activate(ctx, installs[install])
            try:
                find_celeste_asm(path)
            except FileNotFoundError as err:
                raise FileNotFoundError(
                    f"""Install {install} does not have a valid path:
                        {click.style(path + " " + repr(err), "red")}
                        Use `set-path` to assign a new path."""
                )


def install(*param_decls, resolve=True, require_everest=False, **attrs):
    """Alias for a `click.argument` of type `Install` that will use the default provided by `MONS_DEFAULT_INSTALL`

    Requires a command `cls` of `CommandExt`."""
    return click.argument(
        *param_decls,
        type=Install(resolve_install=resolve, require_everest=require_everest),
        cls=OptionalArg,
        default=get_default_install,
        prompt="Install name",
        warning="mons default install set to {default}",
        prompt_envvar="MONS_PROMPT_INSTALL",
        **attrs,
    )


class URL(ParamTypeG[parse.ParseResult]):
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
            if not all((parsed_url.scheme, parsed_url.netloc)):
                self.fail("Invalid URL.", param, ctx)
            if self.valid_schemes and parsed_url.scheme not in self.valid_schemes:
                self.fail(f"URI scheme '{parsed_url.scheme}' not allowed.", param, ctx)

            return parsed_url
        except ValueError:
            self.fail(f"{value} is not a valid URL.", param, ctx)


class OptionExt(click.Option):
    def __init__(self, *args, **attrs):
        name = attrs.pop("name", None)
        super().__init__(*args, **attrs)
        if name:
            self.name = name


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

    def __init__(self, *args, **kwargs) -> None:
        self.usages: t.List[t.List[str]] = kwargs.pop("usages", [])
        self.meta_options: t.OrderedDict[str, t.List[t.Tuple[str, str]]] = kwargs.pop(
            "meta_options", None
        )
        super().__init__(*args, **kwargs)

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
            logger.warning(w)
        return super().invoke(ctx)

    def format_help(self, ctx: click.Context, formatter):
        self.format_usage(ctx, formatter)
        self.format_help_text(ctx, formatter)

        attr_values: t.Dict[click.Option, t.Tuple[bool, bool]] = dict()
        for opt in self.params:
            # if metavar is set, make sure it is used even if the option isn't
            # supposed to accept an argument.
            if isinstance(opt, click.Option) and opt.metavar:
                attr_values[opt] = (opt.is_flag, opt.count)
                opt.is_flag = opt.count = False
        self.format_options(ctx, formatter)
        # reset values
        for opt, vals in attr_values.items():
            opt.is_flag, opt.count = vals

        self.format_meta_options(ctx, formatter)
        self.format_epilog(ctx, formatter)

        formatter.buffer = [format_rst_inline(line) for line in formatter.buffer]

    def format_usage(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        if not self.usages:
            return super().format_usage(ctx, formatter)

        options_metavar = [self.options_metavar] if self.options_metavar else []
        prefix = None
        for usage in self.usages:
            formatter.write_usage(
                ctx.command_path, " ".join(options_metavar + usage), prefix
            )
            prefix = f"   {_('OR:')} "

        # pieces = self.collect_usage_pieces(ctx)
        # formatter.write_usage(ctx.command_path, " ".join(pieces))

    def format_meta_options(self, ctx, formatter):
        if self.meta_options:
            for opt_set, opts in self.meta_options.items():
                with formatter.section(_(opt_set)):
                    formatter.write_dl(opts)
