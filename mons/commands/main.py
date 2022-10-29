import io
import os
import shutil
import subprocess
import typing as t
import urllib.parse
import zipfile

import click
from click import echo

import mons.clickExt as clickExt
import mons.fs as fs
from mons.config import config_dir
from mons.config import CONFIG_FILE
from mons.config import editConfig
from mons.config import pass_userinfo
from mons.config import UserInfo
from mons.downloading import download_with_progress
from mons.errors import TTYError
from mons.formatting import format_columns
from mons.install import Install
from mons.mons import cli
from mons.utils import build_exists
from mons.utils import fetch_build_artifact
from mons.utils import find_celeste_file
from mons.utils import getMD5Hash
from mons.utils import parseVersionSpec
from mons.utils import unpack


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


@cli.command(no_args_is_help=True, cls=clickExt.CommandExt)
@clickExt.install("name")
@click.argument("branch")
def set_branch(name: Install, branch: str):
    """Set the preferred branch name for an existing install"""
    name["PreferredBranch"] = branch
    echo(f"Preferred branch for `{name.name}` is now `{branch}`.")


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


@cli.command(no_args_is_help=True, cls=clickExt.CommandExt)
@clickExt.install("name")
@click.argument("versionSpec", required=False)
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
@click.option(
    "--latest", is_flag=True, help="Install latest available build, branch-ignorant."
)
@click.option("--zip", type=click.File(mode="rb"), help="Install from zip artifact.")
@click.option(
    "--url",
    type=clickExt.URL(require_path=True),
    help="Download and install from a URL.",
)
@click.option(
    "--src",
    cls=clickExt.ExplicitOption,
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Build and install from source folder.",
)
@click.option("--src", cls=clickExt.DefaultOption, is_flag=True)
@click.option(
    "--no-build", is_flag=True, help="Use with --src to install without building."
)
@click.option("--launch", is_flag=True, help="Launch Celeste after installing.")
@pass_userinfo
def install(
    userinfo: UserInfo,
    name: Install,
    versionspec: str,
    verbose: bool,
    latest: bool,
    zip: io.BufferedReader,
    url: t.Optional[urllib.parse.ParseResult],
    src: t.Optional[str],
    src_default: bool,
    no_build: bool,
    launch: bool,
):
    """Install Everest

    VERSIONSPEC can be a branch name, build number, or version number."""
    install = name
    path = install.path
    installDir = os.path.dirname(path)
    success = False

    artifactPath = None
    build = None

    if src_default:
        src = userinfo.config.get("user", "SourceDirectory", fallback=None)
        if not src:
            raise click.BadOptionUsage(
                "--src", "--src option passed with no path and no SourceDirectory set"
            )

    if src:
        build_success = 0 if no_build else 1
        if not no_build:
            if shutil.which("dotnet"):
                build_success = subprocess.run(
                    [
                        "dotnet",
                        "build",
                        "--verbosity",
                        "normal" if verbose else "minimal",
                    ],
                    cwd=src,
                ).returncode
            elif shutil.which("msbuild"):
                build_success = subprocess.run(
                    ["msbuild", "-verbosity:" + ("normal" if verbose else "minimal")],
                    cwd=src,
                ).returncode
            else:
                raise click.ClickException(
                    "Unable to build project: could not find `dotnet` or `msbuild` on PATH.\n"
                    + "Include the --no-build switch to skip build step."
                )

        if build_success == 0:
            echo("Copying files...")
            fs.copy_recursive_force(
                os.path.join(src, "Celeste.Mod.mm", "bin", "Debug", "net452"),
                installDir,
                ignore=lambda path, names: [
                    name
                    for name in names
                    if fs.is_unchanged(
                        os.path.join(path, name), os.path.join(installDir, name)
                    )
                ],
            )
            fs.copy_recursive_force(
                os.path.join(src, "MiniInstaller", "bin", "Debug", "net452"),
                installDir,
                ignore=lambda path, names: [
                    name
                    for name in names
                    if fs.is_unchanged(
                        os.path.join(path, name), os.path.join(installDir, name)
                    )
                ],
            )
            success = True

    elif url:
        download_url = urllib.parse.urlunparse(url)
        echo("Downloading artifact from " + download_url)
        artifactPath = os.path.join(installDir, url.path.split("/")[-1])
        download_with_progress(download_url, artifactPath, atomic=True, clear=True)

    elif zip:
        artifactPath = zip

    if artifactPath:
        label = f"Unzipping {os.path.basename(artifactPath) if isinstance(artifactPath, str) else zip.name}"
        if zip and zip.fileno() == 0:  # stdin
            if zip.isatty():
                raise TTYError("no input.")
            artifactPath = io.BytesIO(zip.read())
        with zipfile.ZipFile(artifactPath) as wrapper:
            try:
                entry = wrapper.open(
                    "olympus-build/build.zip"
                )  # Throws KeyError if not present
                with zipfile.ZipFile(entry) as artifact:
                    unpack(artifact, installDir, label=label)
                    success = True
            except KeyError:
                unpack(wrapper, installDir, "main/", label=label)
                success = True

    elif not src:
        versionspec = "" if latest else (versionspec or install["PreferredBranch"])
        build = parseVersionSpec(versionspec)
        if not build:
            raise click.ClickException(
                f"Build number could not be retrieved for `{versionspec}`."
            )

        if str(build) == install.cache.get("EverestBuild"):
            echo(f"Build {build} already installed.")
            exit(0)

        if not build_exists(build):
            raise click.ClickException(
                f"Build artifacts could not be found for build {build}."
            )

        echo(f"Installing Everest build {build}")
        echo("Downloading build metadata...")
        try:
            meta = fetch_build_artifact(build, "olympus-meta")
            with zipfile.ZipFile(io.BytesIO(meta.read())) as file:
                size = int(file.read("olympus-meta/size.txt"))
        except:
            size = 0

        if size > 0:
            echo("Downloading olympus-build.zip", nl=False)
            response = fetch_build_artifact(build, "olympus-build")
            response.headers["Content-Length"] = str(size)
            artifactPath = os.path.join(installDir, "olympus-build.zip")
            echo(f" to file {artifactPath}")
            download_with_progress(
                response, artifactPath, label="Downloading", clear=True
            )
            with zipfile.ZipFile(artifactPath) as wrapper:
                with zipfile.ZipFile(
                    wrapper.open("olympus-build/build.zip")
                ) as artifact:
                    unpack(artifact, installDir, label="Extracting")
                    success = True

        else:
            echo("Downloading main.zip", nl=False)
            response = fetch_build_artifact(build, "main")
            artifactPath = os.path.join(installDir, "main.zip")
            echo(f" to file {artifactPath}")
            download_with_progress(
                response, artifactPath, label="Downloading", clear=True
            )
            echo("Unzipping main.zip")
            with zipfile.ZipFile(artifactPath) as artifact:
                unpack(artifact, installDir, "main/", label="Extracting")
                success = True

    if success:
        echo("Running MiniInstaller...")
        stdout = None if verbose else subprocess.DEVNULL
        if os.name == "nt":
            installer_ret = subprocess.run(
                os.path.join(installDir, "MiniInstaller.exe"),
                stdout=stdout,
                stderr=None,
                cwd=installDir,
            )
        else:
            uname = os.uname()
            if uname.sysname == "Darwin":
                kickstart_dir = os.path.join(installDir, "..", "MacOS")
                with fs.copied_file(
                    os.path.join(kickstart_dir, "Celeste"),
                    os.path.join(kickstart_dir, "MiniInstaller"),
                ) as miniinstaller:
                    installer_ret = subprocess.run(
                        miniinstaller, stdout=stdout, stderr=None, cwd=installDir
                    )
            else:
                suffix = "x86_64" if uname.machine == "x86_64" else "x86"
                with fs.copied_file(
                    os.path.join(os.path.join(installDir, f"Celeste.bin.{suffix}")),
                    os.path.join(installDir, f"MiniInstaller.bin.{suffix}"),
                ) as miniinstaller:
                    installer_ret = subprocess.run(
                        miniinstaller, stdout=stdout, stderr=None, cwd=installDir
                    )

        if installer_ret.returncode == 0:
            echo("Install success")
            if build:
                peHash = getMD5Hash(path)
                install.cache.update(
                    {
                        "Hash": peHash,
                        "Everest": str(True),
                        "EverestBuild": str(build),
                    }
                )
            else:
                install.update_cache()
                echo("Install info cached")
            if launch:
                echo("Launching Celeste...")
                cli.main(args=["launch", install.name])
            return

    # If we got this far, something went wrong
    click.get_current_context().exit(1)


@cli.command(
    no_args_is_help=True,
    context_settings=dict(
        ignore_unknown_options=True,
        allow_extra_args=True,
    ),
    cls=clickExt.CommandExt,
)
@clickExt.install("name")
@click.argument("args", nargs=-1, required=False, cls=clickExt.PlaceHolder)
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


@cli.command()
@click.option(
    "-e", "--edit", is_flag=True, help="Open the global config file for editing."
)
@click.option("--open", is_flag=True, help="Show the mons config folder.")
@pass_userinfo
def config(userinfo: UserInfo, edit: bool, open: bool):
    """Manage the global config"""
    if edit:
        userinfo.config = editConfig(userinfo.config, CONFIG_FILE)
    elif open:
        click.launch(os.path.join(config_dir, CONFIG_FILE), locate=True)
    else:
        raise click.UsageError(
            """Managing config directly via commandline is not currently supported.
Use --edit to edit the config using the default editor."""
        )
