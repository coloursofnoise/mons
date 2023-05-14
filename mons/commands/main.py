import io
import os
import shutil
import stat
import subprocess
import sys
import typing as t
import urllib.parse
from zipfile import ZipFile

import click
from click import echo
from urllib3 import HTTPResponse

if sys.platform == "linux":
    from mons import overlayfs

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
from mons.utils import find_celeste_asm
from mons.utils import getMD5Hash
from mons.utils import unpack
from mons.version import NOVERSION
from mons.version import Version


@cli.command(no_args_is_help=True)
@click.argument("name", type=clickExt.Install(exist=False))
@click.argument("path", type=click.Path())
@click.option(
    "--overlay",
    type=click.Path(exists=True, resolve_path=True),
    metavar="BASEINSTALL",
    help="Overlay this install on top of BASEINSTALL.",
    hidden=sys.platform != "linux",
)
@pass_userinfo
@click.pass_context
def add(
    ctx: click.Context,
    user_info: UserInfo,
    name: str,
    path: str,
    overlay: t.Optional[fs.Path] = None,
):
    """Add a Celeste install"""
    if overlay and sys.platform == "linux":
        return add_overlay(user_info, name, path, overlay)

    # This can't be done as during argument parsing because when `--overlay` is used the path doesn't have to exist yet.
    path = clickExt.type_cast_value(
        ctx, click.Path(exists=True, resolve_path=True), path
    )
    assert fs.isdir(path) or fs.isfile(path)

    try:
        install_path = fs.dirname(find_celeste_asm(path))
    except FileNotFoundError as err:
        raise click.UsageError(str(err))

    new_install = Install(name, install_path)
    user_info.installs[name] = new_install

    echo(f"Found Celeste install: {install_path}")
    echo(new_install.version_string())


if sys.platform == "linux":

    def add_overlay(
        user_info: UserInfo, name: str, install_path: str, overlay: fs.Path
    ):
        try:
            overlay_path = fs.dirname(find_celeste_asm(overlay))
        except FileNotFoundError as err:
            raise click.UsageError(str(err))

        os.makedirs(install_path, exist_ok=True)
        assert fs.isdir(install_path)
        new_install = Install(name, install_path, overlay_base=overlay_path)
        overlayfs.setup(new_install)

        user_info.installs[name] = new_install
        echo(f"Found Celeste install: {install_path}")
        # The overlay won't be mounted yet, and we don't want to try to activate it
        # right now. Luckily since it's brand-new there will be no changes from the
        # overlay base.
        new_install.path = overlay_path
        echo(new_install.version_string())
        new_install.path = install_path


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
def set_path(name: Install, path: fs.Path):
    """Change the path of an existing install"""
    try:
        install_path = fs.dirname(find_celeste_asm(path))
    except FileNotFoundError as err:
        raise click.UsageError(str(err))

    name.path = install_path
    echo(f"Found Celeste install: {install_path}")
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


@cli.command(name="list")
# @click.option("--json", is_flag=True, hidden=True)
@pass_userinfo
@click.pass_context
def list_cmd(ctx: click.Context, userInfo: UserInfo):
    """List existing installs"""
    output = {}
    if not userInfo.installs:
        raise click.ClickException("No installs found, use `add` to add one.")

    for name, install in userInfo.installs.items():
        try:
            clickExt.Install.validate_install(ctx, name, validate_path=True)
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
        if fs.isfile(orig_exe):
            output["vanilla hash"] = getMD5Hash(orig_exe)
        output["path"] = install.path
        echo(format_columns(output, prefix="\t"))
    else:
        echo("{}:\t{}".format(install.name, install.version_string()))
        echo(install.path)


def build_source(
    srcdir: str,
    dest: str,
    publish: bool,
    verbose: bool,
    configuration_target: t.Optional[str],
    build_args: t.List[str],
):
    framework = configuration = None
    if configuration_target:
        configuration, framework = configuration_target.split("/")

    if shutil.which("dotnet"):
        build_command = [
            "dotnet",
            "publish" if publish else "build",

            "--verbosity",     "normal"  if verbose else "minimal",
         *(("--configuration", configuration) if configuration else ()),
         *(("--framework",     framework)     if framework     else ()),
            "--output",        dest,
            *build_args,
        ]  # fmt: skip

        if verbose:
            echo(" ".join(build_command))
        return (
            subprocess.run(
                build_command,
                cwd=srcdir,
            ).returncode
            == 0
        )
    elif shutil.which("msbuild"):
        build_command = [
            "msbuild",

          *("-target:"    +  "Publish" if publish else ()),
            "-verbosity:" + ("normal"  if verbose else "minimal"),

          *("-property:"  +  "Configuration=" + configuration if configuration else ()),
          *("-property:"  +  "Framework="     + framework if framework else ()),
            "-property:"  +  "OutDir="        + dest,
            *build_args,
        ]  # fmt: skip

        if verbose:
            echo(" ".join(build_command))
        return (
            subprocess.run(
                build_command,
                cwd=srcdir,
            ).returncode
            == 0
        )
    else:
        raise click.ClickException(
            "Unable to build project: could not find `dotnet` or `msbuild` on PATH.\n"
            + "Include the --no-build switch to skip build step."
        )


def determine_configuration(srcdir: fs.Directory):
    """Use heuristics to determine which build output (Configuration/Target) to copy.

    :return: Returns the most recently modified output that is shared between all projects in `srcdir`.
    """
    artifacts: t.Dict[str, t.Set[str]] = dict()

    # Find project dirs
    for proj in os.listdir(srcdir):
        if not fs.isfile(os.path.join(srcdir, proj, proj + ".csproj")):
            continue

        bindir = os.path.join(srcdir, proj, "bin")
        if not fs.isdir(bindir):
            raise click.ClickException(
                f"No build artifacts found for project '{proj}'. Make sure to build the project before installing."
            )

        outputs = set()

        # Find all output directories (assuming 'bin/{Configuration}/{Target}') with files in them
        for conf in os.listdir(bindir):
            for target in os.listdir(fs.joindir(bindir, conf)):
                if any(
                    filenames
                    for _, _, filenames in os.walk(fs.joindir(bindir, conf, target))
                ):
                    outputs.add(os.path.join(conf, target))
        if len(outputs) < 1:
            raise click.ClickException(
                f"No build artifacts found for project '{proj}'."
            )
        artifacts[proj] = outputs

    if len(artifacts) < 1:
        raise click.ClickException(
            f"No projects found. Are you sure '{srcdir}' is an Everest source repo?"
        )

    # Get outputs that are shared between all projects
    common_outputs = set.intersection(*[outputs for outputs in artifacts.values()])

    if len(common_outputs) < 1:
        return None

    if len(common_outputs) > 1:
        # Get the artifact that was modified most recently (and presumeably built most recently)
        newest_artifact, _ = max(
            (
                (output, os.stat(fs.joindir(srcdir, p, "bin", output)))
                for (p, outputs) in artifacts.items()
                for output in outputs
            ),
            key=lambda item: item[1],
        )
        return newest_artifact

    # Only one output is shared
    (only_common_output,) = common_outputs
    return only_common_output


def copy_source_artifacts(
    srcdir: fs.Directory,
    explicit_configuration: t.Optional[str],
    dest: str,
    publish=False,
):
    """Copy build artifacts from an Everest source repo."""

    configuration = explicit_configuration or determine_configuration(srcdir)
    if not configuration:
        raise click.ClickException(
            "Could not determine build artifact to copy. Use the '--configuration' option to specify."
        )

    echo(f"Copying files for configuration '{configuration}'.")
    changed_files = 0
    for proj in os.listdir(srcdir):
        if not (
            fs.isfile(os.path.join(srcdir, proj, proj + ".csproj"))
            and fs.isdir(os.path.join(srcdir, proj, "bin"))
        ):
            continue

        output_path = os.path.join(srcdir, proj, "bin", configuration)
        if explicit_configuration and not fs.isdir(output_path):
            echo(
                f"Build artifacts for configuration '{explicit_configuration}' do not exist for project '{proj}'. Skipping project..."
            )
            continue

        artifact_dir = fs.joindir(srcdir, proj, "bin", configuration)
        if publish and fs.isdir(os.path.join(artifact_dir, "publish")):
            artifact_dir = fs.joindir(artifact_dir, "publish")

        # Publish artifacts are added to a 'publish' subfolder, which we want to skip for regular builds.
        def skip_published(dir, filenames: t.List[str]):
            if not publish:
                if os.path.basename(dir) == "publish":
                    return []
                # Let's skip the 'publish' folder too
                return (file for file in filenames if not file == "publish")
            return filenames

        changed_files += fs.copy_changed_files(
            artifact_dir,
            dest,
            filter=skip_published,
        )

    return changed_files


def is_version(string: str):
    try:
        ver = Version.parse(string)
        return not isinstance(ver, NOVERSION)
    except ValueError:
        return False


def fetch_artifact_source(ctx: click.Context, source: t.Optional[str]):
    try:
        url = clickExt.type_cast_value(ctx, clickExt.URL(require_path=True), source)
        if url:
            return str(urllib.parse.urlunparse(url))
    except click.BadParameter:
        pass

    if not source:
        build_list = fetch_build_list(ctx)
        return build_list[0]["mainDownload"]

    if source.startswith("refs/"):
        build = fetch_latest_build_azure(source)
        if build:
            return fetch_build_artifact_azure(build)

    build_list = fetch_build_list(ctx)
    for build in build_list:
        if source == build["branch"]:
            return build["mainDownload"]

    if source.isdigit():
        build_num = int(source)
        for build in build_list:
            if build["version"] == build_num:
                return build["mainDownload"]

    if is_version(source):
        parsed_ver = Version.parse(source)
        for build in build_list:
            if build["version"] == parsed_ver.Minor:
                return build["mainDownload"]

    return None


def download_artifact(url: t.Union[HTTPResponse, str]) -> t.IO[bytes]:
    url_str = str(url.geturl() if isinstance(url, HTTPResponse) else url)
    click.echo("Downloading artifact from " + url_str)
    with fs.temporary_file(persist=True) as file:
        download_with_progress(url, file, clear=True)
        return click.open_file(file, mode="rb")


def extract_artifact(install: Install, artifact: t.IO[bytes]):
    if artifact.fileno() == 0:  # stdin
        if artifact.isatty():
            raise TTYError("no input.")
        artifact = io.BytesIO(artifact.read())

    dest = install.path
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
    install_dir = install.path
    if os.name == "nt":
        return subprocess.run(
            os.path.join(install_dir, "MiniInstaller.exe"),
            stdout=stdout,
            stderr=None,
            cwd=install_dir,
        )

    uname = os.uname()
    if uname.sysname == "Darwin":
        kickstart_dir = fs.joindir(install_dir, "..", "MacOS")
        with fs.copied_file(
            fs.joinfile(kickstart_dir, "Celeste"),
            os.path.join(kickstart_dir, "MiniInstaller"),
        ) as miniinstaller:
            return (
                subprocess.run(
                    miniinstaller, stdout=stdout, stderr=None, cwd=install_dir
                ).returncode
                == 0
            )

    # Linux
    suffix = "x86_64" if uname.machine == "x86_64" else "x86"
    core_miniinstaller = os.path.join(install_dir, "MiniInstaller-linux")
    if fs.isfile(core_miniinstaller):
        # This file may not be marked as executable, especially when building from a zip artifact
        os.chmod(core_miniinstaller, os.stat(core_miniinstaller).st_mode | stat.S_IEXEC)
        return (
            subprocess.run(
                core_miniinstaller, stdout=stdout, stderr=None, cwd=install_dir
            ).returncode
            == 0
        )

    with fs.copied_file(
        fs.joinfile(install_dir, f"Celeste.bin.{suffix}"),
        os.path.join(install_dir, f"MiniInstaller.bin.{suffix}"),
    ) as miniinstaller:
        return (
            subprocess.run(
                miniinstaller, stdout=stdout, stderr=None, cwd=install_dir
            ).returncode
            == 0
        )


def validate_configuration(ctx, param, value: t.Optional[str]):
    if isinstance(value, str) and not len(value.split("/")) == 2:
        raise click.BadParameter("Must be supplied as '[CONFIGURATION]/[TARGET]'")
    return value


@cli.command(
    no_args_is_help=True,
    context_settings=dict(
        ignore_unknown_options=True,
        allow_extra_args=True,
    ),
    cls=clickExt.CommandExt,
    usages=[
        ["NAME", "[VERSIONSPEC | PATH | URL]"],
        ["NAME", "--src", "[--no-build]", "[PATH] [BUILD ARGS...]"],
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
    "--configuration",
    help="Configuration/Framework to build for.",
    callback=validate_configuration,
)
@click.option(
    "--publish/--no-publish",
    default=False,
    help="Invoke the 'Publish' target when building.",
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
    configuration: t.Optional[str],
    publish: bool,
    launch_game: bool,
):
    """Install Everest

    VERSIONSPEC can be a branch name, build number, or version number."""
    # Additional option validation
    if not src:
        for opt, val in [
            ("no-build", no_build),
            ("configuration", configuration),
            ("publish", publish),
        ]:
            if val:
                raise click.BadOptionUsage(
                    f"--{opt}", "--{opt} can only be used with the --src option.", ctx
                )

    if src and not source:
        source = userinfo.config.source_directory
        if not source:
            raise click.BadOptionUsage(
                "--src",
                "--src option passed with no path or 'source_directory' configuration value.",
                ctx,
            )

    # Install command start
    if src:
        source_dir = fs.Directory(
            clickExt.type_cast_value(
                ctx,
                click.Path(
                    exists=True, file_okay=False, readable=True, resolve_path=True
                ),
                source,
            )
        )
        if not no_build:
            echo("Building Everest source...")
            # Build source straight to install path
            build_source(
                source_dir,
                install.path,
                publish,
                verbose,
                configuration,
                build_args=userinfo.config.build_args + ctx.args,
            )
        else:
            echo("Copying new and updated files...")
            copied = copy_source_artifacts(
                source_dir, configuration, install.path, publish
            )
            if copied == 0:
                echo("No files were changed.")
            else:
                echo(f"Copied {copied} files.")
        artifact = None
    elif source and fs.isfile(source):
        artifact = clickExt.type_cast_value(ctx, click.File(mode="rb"), source)

    else:
        source_download = fetch_artifact_source(ctx, source)
        if not source_download:
            raise click.BadParameter(
                f"Provided build or branch '{source}' does not exist.",
                ctx,
                param_hint="source",
            )
        artifact = download_artifact(source_download)

    if artifact:
        extract_artifact(install, artifact)

    echo("Running MiniInstaller...")
    if not run_installer(install, verbose):
        raise click.ClickException(
            "Installing Everest failed, consult the MiniInstaller log for details."
        )
    echo("Everest was installed.")

    # install.update_cache(read_exe=True)
    # if install.everest_version != version:
    #    echo(f"Warning: Requested and installed versions do not match! ({install.everest_version} != {version})"

    if launch_game:
        echo("Launching Celeste...")
        ctx.invoke(launch, name=install)


if sys.platform == "linux":

    @cli.command(no_args_is_help=True)
    @clickExt.install("name")
    @click.pass_context
    def uninstall(ctx, name: Install):
        """Uninstall Everest from an overlay install."""
        if not name.overlay_base:
            raise click.UsageError(
                "Uninstalling is currently only supported for overlay installs."
            )
        overlayfs.reset(ctx, name)


# fmt: off
everest_core_filenames = [
    "apphosts", "everest-lib",
    "lib64-win-x64", "lib64-win-x86", "lib64-linux", "lib64-osx",
    "Celeste.dll", "Celeste.runtimeconfig.json",
    "Celeste.deps.json", "Celeste.Mod.mm.deps.json", "NETCoreifier.deps.json",
    "MiniInstaller-win.exe", "MiniInstaller-win64.exe", "MiniInstaller-linux", "MiniInstaller-osx", "MiniInstaller-win.exe.manifest",
    "MiniInstaller.dll", "MiniInstaller.runtimeconfig.json", "MiniInstaller.deps.json",
    "NETCoreifier.dll", "NETCoreifier.pdb", "NETCoreifier.deps.json",

    "MonoMod.Backports.dll", "MonoMod.Backports.pdb", "MonoMod.Backports.xml",
    "MonoMod.Core.dll", "MonoMod.Core.pdb", "MonoMod.Core.xml",
    "MonoMod.Iced.dll", "MonoMod.Iced.pdb", "MonoMod.Iced.xml",
    "MonoMod.ILHelpers.dll", "MonoMod.ILHelpers.pdb",
    "MonoMod.RuntimeDetour.pdb", "MonoMod.RuntimeDetour.xml",
    "MonoMod.Utils.pdb", "MonoMod.Utils.xml",
    "MonoMod.Patcher", "MonoMod.Patcher.runtimeconfig.json",
    "MonoMod.Patcher.dll", "MonoMod.Patcher.pdb", "MonoMod.Patcher.xml",
    "MonoMod.RuntimeDetour.HookGen", "MonoMod.RuntimeDetour.HookGen.runtimeconfig.json",
    "MonoMod.RuntimeDetour.HookGen.dll", "MonoMod.RuntimeDetour.HookGen.pdb", "MonoMod.RuntimeDetour.HookGen.xml",
]

everest_backup_exclude = [
    "Content", "Saves",
]
# fmt: on


@cli.command(hidden=True)
@clickExt.install("name")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
def downgrade_core(name: Install, verbose: bool):
    """Use when downgrading from a .NET Core build.

    Cleans up and restores some files that are added or changed in the .NET Core build.

    WARNING: This command will leave the install in an unstable state.
    Make sure to re-install Everest after running it.
    """
    echo("Removing residual .NET Core files...")
    for filename in everest_core_filenames:
        path = os.path.join(name.path, filename)
        if fs.isfile(path):
            os.remove(path)
        elif fs.isdir(path):
            shutil.rmtree(path)
        else:
            continue
        if verbose:
            echo(path)

    echo("Restoring backup...")
    restore_dest = name.path
    for filename in os.listdir(os.path.join(restore_dest, "orig")):
        if filename in everest_backup_exclude:
            continue

        orig_path = os.path.join(restore_dest, "orig", filename)
        dest_path = os.path.join(restore_dest, filename)

        # MacOS is special
        if sys.platform == "darwin":
            macos_path = os.path.join(os.path.dirname(name.path), "MacOS")
            if filename.casefold() == "Celeste".casefold():
                restore_dest = os.path.join(macos_path, "Celeste")
            elif filename.casefold() == "osx".casefold():
                restore_dest = os.path.join(macos_path, "osx")

        if fs.isfile(orig_path):
            if fs.isfile(dest_path):
                os.remove(dest_path)
            os.rename(orig_path, dest_path)
        elif fs.isdir(orig_path):
            if fs.isdir(dest_path):
                shutil.rmtree(dest_path)
            os.rename(orig_path, dest_path)
        else:
            continue
        if verbose:
            echo(orig_path + " -> " + dest_path)


@cli.command(
    no_args_is_help=True,
    context_settings=dict(
        ignore_unknown_options=True,
        allow_extra_args=True,
    ),
    meta_options={
        "Game Arguments": [
            ("--console", "Attach output of game process (implies --wait)."),
            ("--vanilla", "Launche Celeste without Everest."),
        ]
    },
    cls=clickExt.CommandExt,
)
@clickExt.install("name", metavar="NAME [ARGS]...")
@click.option("--wait", is_flag=True, help="Wait for game process to exit.")
@click.option("--dry-run", is_flag=True, hidden=True)
@click.pass_context
def launch(ctx: click.Context, name: Install, wait: bool, dry_run: bool):
    """Launch the game associated with an install

    Any additional arguments are passed to the launched process."""
    path = name.asm
    if os.name != "nt":
        if os.uname().sysname == "Darwin":
            path = fs.File(
                os.path.normpath(os.path.join(name.path, "..", "MacOS", "Celeste"))
            )
        else:
            path = fs.File(os.path.splitext(path)[0])  # drop the .exe

    launch_args = ctx.ensure_object(UserInfo).config.launch_args
    launch_args += ctx.args

    redirect = subprocess.PIPE
    if "--console" in launch_args:
        redirect = None
        wait = True

    if dry_run:
        echo(" ".join([path] + launch_args))
        exit(0)

    proc = subprocess.Popen([path] + launch_args, stdout=redirect, stderr=redirect)
    if wait:
        proc.wait()
