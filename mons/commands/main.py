import io
import os
import shutil
import subprocess
import typing as t
import urllib.parse
from zipfile import ZipFile

import click
from click import echo

import mons.clickExt as clickExt
import mons.fs as fs
from mons.config import pass_userinfo
from mons.config import UserInfo
from mons.downloading import download_with_progress
from mons.errors import TTYError
from mons.formatting import format_columns
from mons.install import Install
from mons.mons import cli
from mons.sources import fetch_build_artifact_azure
from mons.sources import fetch_build_list
from mons.sources import fetch_latest_build_azure
from mons.utils import find_celeste_file
from mons.utils import getMD5Hash
from mons.utils import unpack
from mons.version import NOVERSION
from mons.version import Version


@cli.command(no_args_is_help=True)
@click.argument("name", type=clickExt.Install(exist=False))
@click.argument("path", type=click.Path(exists=True, resolve_path=True))
@pass_userinfo
def add(userInfo: UserInfo, name: str, path: str):
    """Add a Celeste install"""
    try:
        install_path = find_celeste_file(path, "Celeste.exe")
    except FileNotFoundError as err:
        raise click.UsageError(str(err))

    new_install = Install(name, install_path)
    userInfo.installs[name] = new_install

    echo(f"Found Celeste.exe: {install_path}")
    echo(new_install.version_string())


@cli.command(no_args_is_help=True)
@click.argument("name", type=clickExt.Install())
@click.option(
    "-e",
    "--eval",
    is_flag=True,
    help="Print `export MONS_DEFAULT_INSTALL={NAME}` to stdout.",
)
def use(name: str, eval: bool):
    """Set the default install for mons commands

    To un-set, run `export MONS_DEFAULT_INSTALL=`"""
    if eval:
        echo(f"export MONS_DEFAULT_INSTALL={name}")
    else:
        echo(
            f"""Mons can't set environment variables in the parent shell.
To circumvent this, run the following:

eval "$(mons use {name} --eval)" """,
            err=True,
        )


@cli.command(no_args_is_help=True)
@click.argument("old", type=clickExt.Install(exist=True))
@click.argument("new", type=clickExt.Install(exist=False))
@pass_userinfo
def rename(userInfo: UserInfo, old: str, new: str):
    """Rename a Celeste install"""
    userInfo.installs[new] = userInfo.installs.pop(old)
    userInfo.installs[new].name = new
    echo(f"Renamed install `{old}` to `{new}`")


@cli.command(no_args_is_help=True)
@click.argument("name", type=clickExt.Install(check_path=False, resolve_install=True))
@click.argument("path", type=click.Path(exists=True, resolve_path=True))
def set_path(name: Install, path: str):
    """Change the path of an existing install"""
    try:
        install_path = find_celeste_file(path, "Celeste.exe")
    except FileNotFoundError as err:
        raise click.UsageError(str(err))

    name.path = install_path
    echo(f"Found Celeste.exe: {install_path}")
    echo(name.version_string())


@cli.command(
    no_args_is_help=True,
)
@click.argument("name", type=clickExt.Install(check_path=False))
@click.confirmation_option(
    "--force",
    prompt="Are you sure you want to remove this install?",
    help="Skip confirmation prompt.",
)
@pass_userinfo
def remove(userInfo: UserInfo, name: str):
    """Remove an existing install"""
    del userInfo.installs[name]
    echo(f"Removed install {name}.")


@cli.command()
# @click.option("--json", is_flag=True, hidden=True)
@pass_userinfo
def list(userInfo: UserInfo):
    """List existing installs"""
    output = {}
    if not userInfo.installs:
        raise click.ClickException("No installs found, use `add` to add one.")

    for name, install in userInfo.installs.items():
        try:
            clickExt.Install.validate_install(name, validate_path=True)
            output[name] = install.version_string()
        except Exception as err:
            raise click.UsageError(str(err))

    click.echo(format_columns(output))


@cli.command(cls=clickExt.CommandExt, no_args_is_help=True)
@clickExt.install("name")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
def show(name: Install, verbose: bool):
    """Display information for a specific install"""
    install = name
    install.update_cache(read_exe=True)
    if verbose:
        echo(install.name + ":")
        output = {**install.get_cache()}
        orig_exe = os.path.join(os.path.dirname(install.path), "orig", "Celeste.exe")
        if os.path.isfile(orig_exe):
            output["vanilla hash"] = getMD5Hash(orig_exe)
        output["path"] = install.path
        echo(format_columns(output, prefix="\t"))
    else:
        echo("{}:\t{}".format(install.name, install.version_string()))
        echo(install.path)


def build_source(srcdir: str, verbose=False):
    if shutil.which("dotnet"):
        return (
            subprocess.run(
                [
                    "dotnet",
                    "build",
                    "--verbosity",
                    "normal" if verbose else "minimal",
                ],
                cwd=srcdir,
            ).returncode
            == 0
        )
    elif shutil.which("msbuild"):
        return (
            subprocess.run(
                ["msbuild", "-verbosity:" + ("normal" if verbose else "minimal")],
                cwd=srcdir,
            ).returncode
            == 0
        )
    else:
        raise click.ClickException(
            "Unable to build project: could not find `dotnet` or `msbuild` on PATH.\n"
            + "Include the --no-build switch to skip build step."
        )


def copy_source_artifacts(srcdir: str, dest: str):
    echo("Copying files...")
    fs.copy_recursive_force(
        os.path.join(srcdir, "Celeste.Mod.mm", "bin", "Debug", "net452"),
        dest,
        ignore=lambda path, names: [
            name
            for name in names
            if fs.is_unchanged(os.path.join(path, name), os.path.join(dest, name))
        ],
    )
    fs.copy_recursive_force(
        os.path.join(srcdir, "MiniInstaller", "bin", "Debug", "net452"),
        dest,
        ignore=lambda path, names: [
            name
            for name in names
            if fs.is_unchanged(os.path.join(path, name), os.path.join(dest, name))
        ],
    )
    return True


def is_version(string: str):
    try:
        ver = Version.parse(string)
        return not isinstance(ver, NOVERSION)
    except:
        return False


def download_artifact(ctx: click.Context, version: t.Optional[str]) -> t.IO[bytes]:
    dummy_option = click.Option("-d")

    dummy_option.type = click.File(mode="rb")
    try:
        file = dummy_option.type_cast_value(ctx, version)
        if file:
            return file
    except click.BadParameter:
        pass

    def get_url():
        dummy_option.type = clickExt.URL(require_path=True)
        try:
            url = dummy_option.type_cast_value(ctx, version)
            if url:
                return str(urllib.parse.urlunparse(url))
        except click.BadParameter:
            pass

        if not version:
            build_list = fetch_build_list(ctx)
            return build_list[0]["mainDownload"]

        if version.startswith("refs/"):
            build = fetch_latest_build_azure(version)
            if build:
                return fetch_build_artifact_azure(build)

        build_list = fetch_build_list(ctx)
        branches = {build["branch"]: build for build in build_list}
        if version in branches:
            return branches[version]["mainDownload"]

        if version.isdigit():
            build_num = int(version)
            for build in build_list:
                if build["version"] == build_num:
                    return build["mainDownload"]

        if is_version(version):
            parsed_ver = Version.parse(version)
            for build in build_list:
                if build["version"] == parsed_ver.Minor:
                    return build["mainDownload"]

        raise click.ClickException("")

    url = get_url()
    if not url:
        raise click.BadParameter("you failed!")

    click.echo("Downloading artifact from " + str(url))
    with fs.temporary_file(persist=True) as file:
        download_with_progress(url, file, clear=True)
        return click.open_file(file, mode="rb")


def extract_artifact(install: Install, artifact: t.IO[bytes]):
    if artifact.fileno() == 0:  # stdin
        if artifact.isatty():
            raise TTYError("no input.")
        artifact = io.BytesIO(artifact.read())

    dest = install.dir
    with ZipFile(artifact) as wrapper:
        try:
            entry = wrapper.open(
                "olympus-build/build.zip"
            )  # Throws KeyError if not present
            with ZipFile(entry) as nested:
                unpack(nested, dest)
        except KeyError:
            unpack(wrapper, dest, "main/")


def run_installer(install: Install, verbose: bool):
    stdout = None if verbose else subprocess.DEVNULL
    install_dir = install.dir
    if os.name == "nt":
        installer_ret = subprocess.run(
            os.path.join(install_dir, "MiniInstaller.exe"),
            stdout=stdout,
            stderr=None,
            cwd=install_dir,
        )
    else:
        uname = os.uname()
        if uname.sysname == "Darwin":
            kickstart_dir = os.path.join(install_dir, "..", "MacOS")
            with fs.copied_file(
                os.path.join(kickstart_dir, "Celeste"),
                os.path.join(kickstart_dir, "MiniInstaller"),
            ) as miniinstaller:
                return (
                    subprocess.run(
                        miniinstaller, stdout=stdout, stderr=None, cwd=install_dir
                    ).returncode
                    == 0
                )
        else:
            suffix = "x86_64" if uname.machine == "x86_64" else "x86"
            with fs.copied_file(
                os.path.join(os.path.join(install_dir, f"Celeste.bin.{suffix}")),
                os.path.join(install_dir, f"MiniInstaller.bin.{suffix}"),
            ) as miniinstaller:
                return (
                    subprocess.run(
                        miniinstaller, stdout=stdout, stderr=None, cwd=install_dir
                    ).returncode
                    == 0
                )


@cli.command(
    no_args_is_help=True,
    cls=clickExt.CommandExt,
    usages=[
        ["NAME", "[VERSIONSPEC | PATH | URL]"],
        ["NAME", "--src", "[--no-build]", "[PATH]"],
    ],
)
@clickExt.install("install", metavar="NAME")
@click.argument("source", required=False)
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
@click.option(
    "--latest", is_flag=True, help="Install latest available build, branch-ignorant."
)
@click.option(
    "--src",
    is_flag=True,
    help="Build and install from source folder.",
)
@click.option(
    "--no-build", is_flag=True, help="Use with --src to install without building."
)
@click.option(
    "--launch",
    name="launch_game",
    is_flag=True,
    help="Launch Celeste after installing.",
    cls=clickExt.OptionExt,
)
@pass_userinfo
@click.pass_context
def install(
    ctx: click.Context,
    userinfo: UserInfo,
    install: Install,
    source: t.Optional[str],
    verbose: bool,
    latest: bool,
    src: bool,
    no_build: bool,
    launch_game: bool,
):
    """Install Everest

    VERSIONSPEC can be a branch name, build number, or version number."""
    if no_build and not src:
        raise click.BadOptionUsage(
            "--no-build", "--no-build can only be used with the --src option.", ctx
        )

    if src and not source:
        source = userinfo.config.source_directory
        if not source:
            raise click.BadOptionUsage(
                "--src",
                "--src option passed with no path or 'source_directory' configuration value.",
                ctx,
            )

    if src:
        source_dir = clickExt.type_cast_value(
            ctx,
            click.Path(exists=True, file_okay=False, readable=True, resolve_path=True),
            source,
        )
        if not no_build:
            build_source(source_dir, verbose)
        copy_source_artifacts(source_dir, install.dir)
        artifact = None
    else:
        artifact = download_artifact(ctx, source)

    if artifact:
        extract_artifact(install, artifact)

    click.echo("Running MiniInstaller...")
    if not run_installer(install, verbose):
        ctx.exit(1)

    if launch_game:
        echo("Launching Celeste...")
        ctx.invoke(launch, name=install)


@cli.command(
    no_args_is_help=True,
    context_settings=dict(
        ignore_unknown_options=True,
        allow_extra_args=True,
    ),
    cls=clickExt.CommandExt,
)
@clickExt.install("name", metavar="NAME [ARGS]...")
@click.pass_context
def launch(ctx: click.Context, name: Install):
    """Launch the game associated with an install

    Any additional arguments are passed to the launched process."""
    path = name.path
    if os.name != "nt":
        if os.uname().sysname == "Darwin":
            path = os.path.normpath(
                os.path.join(os.path.dirname(path), "..", "MacOS", "Celeste")
            )
        else:
            path = os.path.splitext(path)[0]  # drop the .exe

    redirect = None if "--console" in ctx.args else subprocess.PIPE

    proc = subprocess.Popen(
        [path] + ctx.args, stdout=redirect, stderr=redirect, shell=True
    )
    if not redirect:
        proc.wait()
