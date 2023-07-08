import itertools
import json
import os
import re
import shutil
import typing as t
import urllib.parse
import urllib.request
from gettext import ngettext
from operator import attrgetter

import click
import yaml
from click import echo

import mons.clickExt as clickExt
import mons.fs as fs
from mons.baseUtils import chain_partition
from mons.baseUtils import invert
from mons.baseUtils import multi_partition
from mons.baseUtils import partition
from mons.baseUtils import read_with_progress
from mons.config import UserInfo
from mons.downloading import download_threaded
from mons.downloading import download_with_progress
from mons.downloading import get_download_size
from mons.downloading import parse_gb_url
from mons.errors import TTYError
from mons.formatting import format_bytes
from mons.install import Install
from mons.logging import ProgressBar
from mons.logging import timed_progress
from mons.modmeta import ModDownload
from mons.modmeta import ModMeta
from mons.modmeta import ModMeta_Base
from mons.modmeta import ModMeta_Deps
from mons.modmeta import read_mod_info
from mons.modmeta import UpdateInfo
from mons.mons import cli as mons_cli
from mons.sources import fetch_dependency_graph
from mons.sources import fetch_mod_db
from mons.sources import fetch_mod_search
from mons.sources import fetch_random_map
from mons.utils import enable_mods
from mons.utils import installed_mods
from mons.utils import read_blacklist
from mons.version import Version


@click.group(name="mods")
@click.pass_context
def cli(ctx: click.Context):
    """Manage Everest mods
    \f

    |full_reference-mods|"""
    pass


mons_cli.add_command(cli)


def format_mod(meta: ModMeta):
    data: t.Dict[str, t.Any] = {
        "Version": str(meta.Version),
    }
    if meta.Size:
        data["Size"] = format_bytes(meta.Size)
    if meta.Path:
        data["Filename"] = os.path.basename(meta.Path)
    if meta.Dependencies:
        data["Dependencies"] = [dep.Name for dep in meta.Dependencies]
    if meta.OptionalDependencies:
        data["OptionalDependencies"] = [dep.Name for dep in meta.OptionalDependencies]
    return yaml.dump(
        {meta.Name: data},
        sort_keys=False,
    )


@cli.command(
    name="list",
    no_args_is_help=True,
    cls=clickExt.CommandExt,
)
@clickExt.install("name", require_everest=True)
@click.option(
    "--enabled/--disabled", help="Filter enabled/disabled mods.", default=None
)
@click.option(
    "--valid/--invalid", help="Filter mods with a valid everest.yaml.", default=None
)
@click.option("--dll/--no-dll", help="Filter mods that register DLLs.", default=None)
@click.option(
    "--dir/--zip",
    "dir",
    flag_value=True,
    help="Filter mods in folders/zips.",
    default=None,
)
@click.option("--no-zip/--no-dir", "dir", flag_value=False, hidden=True, default=None)
@click.option("-d", "--dependency", help="Filter mods by dependency.", metavar="MODID")
@click.option(
    "-s", "--search", help="Filter mods with a regex pattern.", metavar="QUERY"
)
@click.option("-v", "--verbose", is_flag=True, help="Print mod details.")
@clickExt.color_option()
def list_mods(
    name: Install,
    enabled: t.Optional[bool],
    valid: t.Optional[bool],
    dll: t.Optional[bool],
    dir: t.Optional[bool],
    dependency: str,
    search: str,
    verbose: bool,
    color: t.Optional[bool],
):
    """List installed mods."""
    if valid is False:
        if dll is True:
            raise click.BadOptionUsage(
                "--dll", "--dll cannot be used with the --invalid flag."
            )
        if dependency:
            raise click.BadOptionUsage(
                "--dependency", "--dependency cannot be used with the --invalid flag."
            )

    gen = installed_mods(
        name.mod_folder, dirs=dir, valid=valid, blacklisted=invert(enabled)
    )

    if dll is not None:
        gen = (meta for meta in gen if not dll ^ bool(meta.DLL))

    if dependency:
        gen = (meta for meta in gen for d in meta.Dependencies if d.Name == dependency)

    if search:
        pattern = re.compile(search, flags=re.I)
        gen = (
            meta
            for meta in gen
            if pattern.search(meta.Name) or pattern.search(os.path.basename(meta.Path))
        )

    def format_line(meta: ModMeta):
        output = f"{meta.Name} {click.style(meta.Version, fg='green')}"
        if meta.Blacklisted:
            output = click.style(output, dim=True) + click.style(
                " (disabled)", dim=True
            )
        return click.style(output + "\n", bold=True)

    def format_verbose(meta: ModMeta):
        formatted = format_mod(meta).splitlines()
        formatted[0] = click.style(formatted[0], bold=True)
        return "\n".join(formatted) + "\n" * 2

    formatter = format_verbose if verbose else format_line
    gen = map(formatter, gen)

    clickExt.echo_via_pager(ProgressBar(gen, "Reading mods..."), color=color)


@cli.command(hidden=True)
@click.argument("search")
@click.pass_context
def search(ctx, search: str):
    mod_list = fetch_mod_db(ctx)
    if search in mod_list:
        echo(mod_list[search]["GameBananaId"])
        return

    search_result = fetch_mod_search(search)
    for item in search_result:
        match = [
            mod
            for mod, data in mod_list.items()
            if data["GameBananaId"] == item["GameBananaId"]
        ]
        for m in match:
            echo(m)
        if len(match) < 1:
            raise click.UsageError("Entry not found: " + str(item["GameBananaId"]))


def search_mods(ctx, search):
    mod_list = fetch_mod_db(ctx)
    search_result = fetch_mod_search(search)
    matches = {}
    for item in search_result:
        matches.update(
            {
                mod: data
                for mod, data in mod_list.items()
                if data["GameBananaId"] == item["GameBananaId"]
            }
        )

    if len(matches) < 1:
        echo("No results found.")
        exit()

    match = prompt_mod_selection(matches, max=9)
    if not match:
        raise click.Abort()
    return match


def prompt_mod_selection(options: t.Dict[str, t.Any], max=-1):
    matchKeys = sorted(
        options.keys(), key=lambda key: options[key]["LastUpdate"], reverse=True
    )
    selection = None
    if len(matchKeys) == 1:
        key = matchKeys[0]
        echo(f'Mod found: {key} {options[key]["Version"]}')
        options[key]["Name"] = key
        selection = ModDownload(options[key], options[key]["URL"])

    if len(matchKeys) > 1:
        echo("Mods found:")
        idx = 1
        for key in matchKeys:
            if max > -1 and idx > max:
                break
            echo(f'  [{idx}] {key} {options[key]["Version"]}')
            idx += 1

        choice = click.prompt(
            "Select mod to add",
            type=click.IntRange(0, idx),
            default=0,
            show_default=False,
        )
        if choice:
            key = matchKeys[choice - 1]
            echo(f'Selected mod: {key} {options[key]["Version"]}')
            options[key]["Name"] = key
            selection = ModDownload(
                options[key], options[key]["URL"], options[key]["Mirror"]
            )

    return selection


def resolve_dependencies(
    mods: t.Sequence[ModMeta], check_versions=True
) -> t.Tuple[t.List[ModMeta_Base], t.List[ModMeta_Base]]:
    """Resolves the dependency tree for a list of mods, as well as the optional dependencies of the tree.

    Optional dependencies are not resolved recursively.

    :raises ValueError: Raises 'ValueError' if incompatible dependencies are encountered.
    This can be differing major versions, or one of the :param:`mods` not satisfying a required dependency.
    """

    dependencies: t.Dict[str, ModMeta_Base] = {}
    opt_dependencies: t.Dict[str, ModMeta_Base] = {}
    dependency_graph = fetch_dependency_graph()

    def check_supersedes(mod, compare, mod_optional=False, compare_optional=False):
        if not check_versions:
            return False
        try:
            return mod.Version.supersedes(compare.Version)
        except ValueError:
            mod_str = str(mod) + (" (optional)" if mod_optional else "")
            compare_str = str(compare) + (" (optional)" if compare_optional else "")
            raise ValueError(
                "Incompatible dependencies encountered: "
                + f"{mod_str} has a different major version to {compare_str}"
            )

    def recurse_dependencies(mod: t.Union[ModMeta_Base, ModMeta_Deps]):
        """Recursively resolve the highest required versions of the dependencies for a mod.

        :raises ValueError: Raises `ValueError` for different major versions of the same dependency.
        :raises RecursionError: Raises `RecursionError` for cyclical dependencies.
        """
        if not isinstance(mod, ModMeta_Deps):
            if mod.Name not in dependency_graph:
                return
            mod = ModMeta_Deps.parse(dependency_graph[mod.Name])

        for dep in mod.Dependencies:
            if dep.Name in dependencies:
                if not check_supersedes(dep, dependencies[dep.Name]):
                    continue
            dependencies[dep.Name] = dep
            recurse_dependencies(dep)

    for mod in mods:
        # 'dependencies' is populated within the function, recursion is messy
        recurse_dependencies(mod)

    # Without version checking, dependencies should be returned as-is.
    # FIXME: This means that the list of dependencies can differ depending on
    # `check_versions` due to redundant (optional)dependencies being removed,
    # which could be misleading.
    # This should be clearly documented, or this function should be split up
    # to require handling version checks (and discarding redundant
    # dependencies) explicitly.
    if not check_versions:
        return list(dependencies.values()), list(opt_dependencies.values())

    # Collect optional dependencies for requested mods and their dependencies.
    # Optional dependencies are not resolved recursively. If they are going to be
    # installed as non-optional dependencies they will already have been recursively resolved.
    dep_deps = (
        dep
        if isinstance(dep, ModMeta_Deps)
        else ModMeta_Deps.parse(dependency_graph[name])
        for name, dep in dependencies.items()
        if isinstance(dep, ModMeta_Deps) or name in dependency_graph
    )

    for opt_dep in itertools.chain.from_iterable(
        mod.OptionalDependencies for mod in itertools.chain(mods, dep_deps)
    ):
        if opt_dep.Name in dependencies:
            # Optional dependencies need to be satisfied if the mod is loaded as a dependency
            if check_supersedes(opt_dep, dependencies[opt_dep.Name], mod_optional=True):
                dependencies[opt_dep.Name] = opt_dep
                continue
        if opt_dep.Name in opt_dependencies:
            if not check_supersedes(
                opt_dep, opt_dependencies[opt_dep.Name], True, True
            ):
                continue
        opt_dependencies[opt_dep.Name] = opt_dep

    # Check if any explicitly requested mods conflict with a required dependency.
    # Also check optional dependencies because they would conflict if the dep
    # is loaded but does not satisfy the version.
    # (Optional) dependencies that will be filled by an explicit mod are dropped.
    for mod in mods:
        if mod.Name in dependencies:
            dep = dependencies[mod.Name]
            # if an explicitly requested mod does not satisfy another's
            # dependency on it, raise an error
            if not mod.Version.satisfies(dep.Version):
                raise ValueError(
                    "Incompatible dependencies encountered: "
                    + f"{mod} (explicit) does not satisfy dependency {dep}"
                )
            # dependency will be filled by an explicitly requested mod
            del dependencies[mod.Name]

        elif mod.Name in opt_dependencies:
            dep = opt_dependencies[mod.Name]
            # if an explicitly requested mod does not satisfy another's
            # dependency on it, raise an error
            if not mod.Version.satisfies(dep.Version):
                raise ValueError(
                    "Incompatible dependencies encountered: "
                    + f"{mod} (explicit) does not satisfy optional dependency {dep}"
                )
            # dependency will be filled by an explicitly requested mod
            del opt_dependencies[mod.Name]

    return list(dependencies.values()), list(opt_dependencies.values())


def get_mod_download(mod: str, mod_list: t.Dict[str, t.Any]):
    mod_info = mod_list[mod]
    mod_info["Name"] = mod
    return ModDownload(ModMeta(mod_info), mod_info["URL"], mod_info["MirrorURL"])


def path_as_url(path: fs.Path):
    return urllib.parse.urlunparse(
        urllib.parse.ParseResult("file", "localhost", path, "", "", "")
    )


def resolve_mods(ctx, mods: t.Sequence[str]):
    resolved: t.List[ModDownload] = list()
    unresolved: t.List[str] = list()
    mod_list = fetch_mod_db(ctx)
    dep_db = fetch_dependency_graph()

    for mod in mods:
        # backwards compat shim
        if mod.startswith("https://gamebanana.com/dl"):
            mod = mod.replace(
                "https://gamebanana.com/dl", "https://gamebanana.com/mmdl"
            )

        parsed_url = urllib.parse.urlparse(mod)
        download = None
        url = None

        db_matches = {key: val for key, val in mod_list.items() if mod == val["URL"]}
        if db_matches:
            download = prompt_mod_selection(db_matches)

        # Special case to try to resolve 1-Click install links through mod database
        if parsed_url.scheme == "everest":
            gb_url = parse_gb_url(parsed_url.path)
            if gb_url:
                matches = {
                    key: val for key, val in mod_list.items() if gb_url == val["URL"]
                }
                if len(matches) > 0:
                    download = prompt_mod_selection(matches)
                else:
                    parsed_url = urllib.parse.urlparse(gb_url)

        # Install from local filesystem
        if mod.endswith(".zip") and os.path.exists(mod):
            parsed_url = urllib.parse.ParseResult(
                "file", "", os.path.abspath(mod), "", "", ""
            )
            meta = read_mod_info(parsed_url.path)
            if meta:
                download = ModDownload(
                    meta,
                    urllib.parse.urlunparse(parsed_url),  # type:ignore
                )
                echo(f"Mod found: {meta}")

        # Mod ID match
        elif mod in mod_list:
            mod_info = mod_list[mod]
            mod_info["Name"] = mod
            download = ModDownload(
                ModMeta({**mod_info, **dep_db[mod]}),
                mod_info["URL"],
                mod_info["MirrorURL"],
            )
            echo(f'Mod found: {mod} {mod_info["Version"]}')

        # GameBanana submission URL
        elif (
            parsed_url.scheme in ("http", "https")
            and parsed_url.netloc == "gamebanana.com"
            and parsed_url.path.startswith("/mods")
            and parsed_url.path.split("/")[-1].isdigit()
        ):
            modID = int(parsed_url.path.split("/")[-1])
            matches = {
                key: val
                for key, val in mod_list.items()
                if modID == val["GameBananaId"]
            }
            if len(matches) > 0:
                download = prompt_mod_selection(matches)
            else:
                downloads = json.load(
                    download_with_progress(
                        f"https://gamebanana.com/apiv5/Mod/{modID}?_csvProperties=_aFiles",
                        None,
                        "Retrieving download list",
                    )
                )["_aFiles"]
                echo("Available downloads:")
                idx = 1
                for d in downloads:
                    echo(f'  [{idx}] {d["_sFile"]} {d["_sDescription"]}')
                    idx += 1

                selection = click.prompt(
                    "Select file to download",
                    type=click.IntRange(0, idx),
                    default=0,
                    show_default=False,
                )
                if selection:
                    d = downloads[selection - 1]
                    echo(f'Selected file: {d["_sFile"]}')
                    url = str(d["_sDownloadUrl"])
                else:
                    echo("Aborted!")

        # Google Drive share URL
        elif (
            parsed_url.scheme in ("http", "https")
            and parsed_url.netloc == "drive.google.com"
            and parsed_url.path.startswith("/file/d/")
        ):
            file_id = parsed_url.path[len("/file/d/") :].split("/")[0]
            url = "https://drive.google.com/uc?export=download&id=" + file_id

        elif parsed_url.scheme and parsed_url.path:
            url = mod

        # Possible GameBanana Submission ID
        elif mod.isdigit():
            modID = int(mod)
            matches = {
                key: val
                for key, val in mod_list.items()
                if modID == val["GameBananaId"]
            }
            if len(matches) > 0:
                download = prompt_mod_selection(matches)

        if download:
            resolved.append(download)
        elif url:
            unresolved.append(url)
        else:
            raise click.ClickException(f"Mod '{mod}' could not be resolved.")

    return resolved, unresolved


def update_everest(install: Install, required: Version):
    current = install.everest_version
    if current and current.satisfies(required):
        return

    echo(
        f"Installed Everest ({current}) does not satisfy minimum requirement ({required})."
    )
    if clickExt.confirm_ext("Update Everest?", default=True):
        mons_cli.main(args=["install", install.name, str(required)])


@cli.command(no_args_is_help=True, cls=clickExt.CommandExt)
@clickExt.install("install", metavar="NAME", require_everest=True)
@click.argument("mods", nargs=-1)
@click.option(
    "--search", is_flag=True, help="Use the Celeste mod search API to find a mod."
)
@click.option("--random", is_flag=True, help="Install a random mod.")
@click.option(
    "--no-deps", is_flag=True, default=False, help="Skip installing dependencies."
)
@clickExt.yes_option()
@clickExt.force_option()
@click.pass_context
def add(
    ctx: click.Context,
    install: Install,
    mods: t.Tuple[str],
    search=False,
    random=False,
    no_deps=False,
):
    """Add mods.

    MODS can be one or more of: mod ID, local zip, zip URL, 1-Click install link, Google Drive share link, GameBanana page, or GameBanana submission ID.
    """
    if random:
        mods = (fetch_random_map(),)
        echo("Selected a random mod: " + str(mods[0]))

    if not mods:
        echo("No mods to add.")
        exit()

    resolved: t.List[ModDownload] = []
    unresolved: t.List[str] = []

    if search:
        resolved = [search_mods(ctx, " ".join(mods))]
    elif mods == ("-",):
        # Special case for handling stdin.
        # More code should be shared with unresolved mods handler,
        # since currently the data will be saved to two different temp files.
        with click.open_file("-", mode="rb") as stdin:
            if stdin.isatty():
                raise TTYError("no input.")

            with fs.temporary_file(persist=True) as temp:
                with click.open_file(temp, mode="wb") as file:
                    read_with_progress(
                        stdin,
                        file,
                        label="Reading from stdin",
                        clear_progress=True,
                    )

                file_url = path_as_url(temp)
                meta = read_mod_info(temp)
                if meta:
                    resolved = [ModDownload(meta, file_url)]
                else:
                    unresolved = [file_url]
    else:
        resolved, unresolved = resolve_mods(ctx, mods)

    if unresolved:
        echo("The following mods could not be resolved:")
        for s in unresolved:
            echo(f"\t{s}")

        download_size = sum(get_download_size(url) for url in unresolved)
        echo(
            f"Downloading them all will use up to {format_bytes(download_size)} of disk space."
        )
        if clickExt.confirm_ext(
            "Download and attempt to resolve them before continuing?", default=True
        ):
            non_mods = []
            for url in unresolved:
                with fs.temporary_file(persist=True) as file:
                    # TODO: multithreaded download
                    download_with_progress(url, file, f"Downloading {url}", clear=True)
                    meta = read_mod_info(file)
                    if meta:
                        resolved.append(ModDownload(meta, path_as_url(file)))
                    else:
                        non_mods.append(file)

            for file in non_mods:
                if clickExt.confirm_ext(
                    f"'{file}' does not seem to be an Everest mod.\nInstall anyways?",
                    default=False,
                    dangerous=True,
                ):
                    filename: str = click.prompt("Save as file")
                    if filename:
                        shutil.move(file, os.path.join(install.mod_folder, filename))
            unresolved.clear()

    # no need to calculate folder size since any mods that are unzipped will be skipped
    installed = {
        meta.Name: meta
        for meta in installed_mods(install.mod_folder, folder_size=False)
    }

    resolved_update, resolved = partition(
        lambda m: m.Meta.Name in installed,
        resolved,
    )
    resolved_update = [
        UpdateInfo(
            installed[mod.Meta.Name], mod.Meta.Version, mod.Url, mod.Mirror, mod.Size
        )
        for mod in resolved_update
    ]

    deps, _opt_deps = (
        resolve_dependencies([mod.Meta for mod in resolved])
        if not no_deps
        else ([], [])
    )

    deps_special, deps_missing, deps_outdated, _deps_installed = multi_partition(
        lambda m: m.Name in ("Celeste", "Everest"),
        lambda m: m.Name not in installed,
        lambda m: not installed[m.Name].Version.satisfies(m.Version),
        iterable=deps,
    )
    deps_outdated = (installed[dep.Name] for dep in deps_outdated)
    del deps

    mod_db = fetch_mod_db(ctx)
    deps_unregistered, deps_missing, deps_outdated = chain_partition(
        lambda m: m.Name not in mod_db,
        deps_missing,
        deps_outdated,
    )

    if len(deps_unregistered) > 0:
        echo(f"{len(deps_unregistered)} dependencies could not be found:")
        for mod in deps_unregistered:
            echo(mod)
        if not clickExt.confirm_ext(
            "Install without missing dependencies?",
            default=True,
            dangerous=True,
        ):
            raise click.Abort()
    del deps_unregistered

    deps_update = [
        UpdateInfo(
            installed[dep.Name],
            dep.Version,
            mod_db[dep.Name]["URL"],
            mod_db[dep.Name]["MirrorURL"],
            mod_db[dep.Name]["Size"],
        )
        for dep in deps_outdated
    ]
    deps_install = [get_mod_download(m.Name, mod_db) for m in deps_missing]
    del deps_outdated, deps_missing

    skip_updates, resolved_update, deps_update = chain_partition(
        lambda m: fs.isdir(m.Meta.Path), resolved_update, deps_update
    )
    if skip_updates:
        echo("Unzipped mods will not be updated:")
        for update in skip_updates:
            echo("  " + str(update))
    del skip_updates

    install_count = len(resolved) + len(deps_install)
    if install_count > 0:
        echo(f"{install_count} mods to install:")
        for download in itertools.chain(resolved, deps_install):
            echo("  " + str(download.Meta))
    update_count = len(resolved_update) + len(deps_update)
    if update_count > 0:
        echo(f"{update_count} mods to update:")
        for update in itertools.chain(resolved_update, deps_update):
            echo("  " + str(update))

    if install_count + update_count < 1:
        echo("No mods to install.")
        exit()

    sorted_main_downloads = sorted(
        itertools.chain(resolved, resolved_update), key=attrgetter("Size")
    )
    sorted_dep_downloads = sorted(
        itertools.chain(deps_install, deps_update), key=attrgetter("Size")
    )

    download_size = sum(
        mod.Size
        for mod in itertools.chain(resolved, resolved_update, deps_install, deps_update)
    )
    if download_size >= 0:
        echo(
            f"After this operation, an additional {format_bytes(download_size)} disk space will be used"
        )
    else:
        echo(
            f"After this operation, {format_bytes(abs(download_size))} disk space will be freed"
        )

    if not clickExt.confirm_ext("Continue?", default=True):
        raise click.Abort()

    with timed_progress("Installed mods in {time:.3f} seconds."):
        download_threaded(
            install.mod_folder,
            sorted_dep_downloads,
            sorted_main_downloads,
            ctx.ensure_object(UserInfo).config.downloading.thread_count,
        )

    # retrieve installed mods again since mods may have been added
    installed = {meta.Name: meta for meta in installed_mods(install.mod_folder)}
    # all mods should now be installed
    assert all(
        mod.Meta.Name in installed
        for mod in itertools.chain(resolved, resolved_update, deps_install, deps_update)
    )

    blacklisted = [
        installed[mod.Meta.Name]
        for mod in itertools.chain(resolved, resolved_update, deps_install, deps_update)
        if installed[mod.Meta.Name].Blacklisted
    ]
    if blacklisted:
        echo("The following mods will be automatically removed from the blacklist:")
        echo(" ".join([str(mod) for mod in blacklisted]))
        enable_mods(
            install.mod_folder, *(os.path.basename(mod.Path) for mod in blacklisted)
        )

    everest_min = next(
        (dep.Version for dep in deps_special if dep.Name == "Everest"), None
    )
    if everest_min:
        update_everest(install, everest_min)


def resolve_exclusive_dependencies(
    mods: t.List[ModMeta], installed: t.Dict[str, ModMeta]
):
    mod_names = [mod.Name for mod in mods]
    dependencies, _opt_deps = resolve_dependencies(mods, check_versions=False)
    other_dependencies, _opt_deps = resolve_dependencies(
        [mod for name, mod in installed.items() if name not in mod_names],
        check_versions=False,
    )

    unique_deps = {dep.Name for dep in dependencies}.difference(
        {other.Name for other in other_dependencies}
    )
    return [installed[dep] for dep in unique_deps if dep in installed]


@cli.command(no_args_is_help=True, cls=clickExt.CommandExt)
@clickExt.install("name")
@click.argument("mods", nargs=-1, required=True)
@click.option(
    "-r",
    "--recurse",
    is_flag=True,
    help="Remove all exclusive dependencies recursively.",
)
@clickExt.force_option()
def remove(name: Install, mods: t.List[str], recurse: bool):
    """Remove installed mods."""
    installed_list = installed_mods(name.mod_folder, valid=True, folder_size=True)
    installed_list = {
        meta.Name: meta
        for meta in ProgressBar(
            installed_list, desc="Reading Installed Mods", leave=False, unit=""
        )
    }

    resolved, unresolved = partition(lambda mod: mod in installed_list, mods)

    if len(unresolved) > 0:
        echo("The following mods could not be found, and will not be removed:")
        for mod in unresolved:
            echo(f"\t{mod}")
        if not clickExt.confirm_ext("Continue anyways?", default=False, dangerous=True):
            raise click.Abort()

    metas = [installed_list[mod] for mod in resolved]

    if len(metas) < 1:
        echo("No mods to remove.")
        exit()

    echo(str(len(metas)) + " mods will be removed:")
    for mod in metas:
        echo(f"\t{mod}")

    removable_deps = (
        resolve_exclusive_dependencies(metas, installed_list) if recurse else []
    )
    if removable_deps:
        echo(str(len(removable_deps)) + " dependencies will also be removed:")
        for dep in removable_deps:
            echo(f"\t{dep}")

    total_size = sum(mod.Size for mod in itertools.chain(metas, removable_deps))
    echo(f"After this operation, {format_bytes(total_size)} disk space will be freed.")

    if not clickExt.confirm_ext("Remove mods?", default=True, dangerous=True):
        raise click.Abort()

    folders: t.List[ModMeta] = []
    with click.progressbar(
        label="Deleting files", length=len(removable_deps) + len(metas)
    ) as progress:
        for mod in itertools.chain(removable_deps, metas):
            # This should be handled by catching IsADirectoryError but for some reason it raises PermissionError instead so...
            if os.path.isdir(mod.Path):
                folders.append(mod)
            else:
                os.remove(mod.Path)
            progress.update(1)

    if len(folders) > 0:
        echo("The following unzipped mods were not removed:")
        for mod in folders:
            echo(f"\t{mod} ({os.path.basename(mod.Path)}/)")


@cli.command(no_args_is_help=True, cls=clickExt.CommandExt)
@clickExt.install("name", require_everest=True)
# @click.argument('mod', required=False)
@click.option(
    "--enabled", is_flag=True, help="Update currently enabled mods.", default=None
)
@click.option(
    "--upgrade-only", is_flag=True, help="Only update if new file has a higher version."
)
@clickExt.yes_option()
@click.pass_context
def update(
    ctx: click.Context,
    name: Install,
    enabled: t.Optional[bool],
    upgrade_only: bool,
):
    """Update installed mods."""

    updates: t.List[UpdateInfo] = []
    mod_db = fetch_mod_db(ctx)
    installed = installed_mods(
        name.mod_folder,
        blacklisted=invert(enabled),
        dirs=False,
        valid=True,
        folder_size=True,
        with_hash=True,
    )
    updater_blacklist = os.path.join(name.mod_folder, "updaterblacklist.txt")
    updater_blacklist = fs.isfile(updater_blacklist) and read_blacklist(
        updater_blacklist
    )
    for meta in installed:
        if meta.Name in mod_db and (
            not updater_blacklist
            or os.path.basename(meta.Path) not in updater_blacklist
        ):
            server = mod_db[meta.Name]
            latest_hash = server["xxHash"][0]
            latest_version = Version.parse(server["Version"])
            if (
                meta.Hash
                and latest_hash != meta.Hash
                and (not upgrade_only or latest_version > meta.Version)
            ):
                updates.append(
                    UpdateInfo(
                        meta,
                        latest_version,
                        server["URL"],
                        server["Mirror"],
                        server["Size"],
                    )
                )

    if not updates:
        echo("All mods up to date")
        return

    echo(
        ngettext(
            f"{len(updates)} update found:",
            f"{len(updates)} updates found:",
            len(updates),
        )
    )
    for update in updates:
        echo("  " + str(update))

    update_size = sum(update.Size for update in updates)
    if update_size >= 0:
        echo(
            f"After this operation, an additional {format_bytes(update_size)} disk space will be used"
        )
    else:
        echo(
            f"After this operation, {format_bytes(abs(update_size))} disk space will be freed"
        )

    if not clickExt.confirm_ext("Continue?", default=True):
        raise click.Abort()

    sorted_updates = sorted(updates, key=attrgetter("Size"))
    with timed_progress("Downloaded files in {time:.3f} seconds."):
        download_threaded(
            name.path,
            sorted_updates,
            thread_count=ctx.ensure_object(UserInfo).config.downloading.thread_count,
        )


@cli.command(no_args_is_help=True, cls=clickExt.CommandExt)
@clickExt.install("name", require_everest=True)
# @click.argument('mod', required=False)
@click.option(
    "--enabled", is_flag=True, help="Resolve currently enabled mods.", default=None
)
@click.option("--no-update", is_flag=True, help="Don't update outdated dependencies.")
@clickExt.yes_option()
def resolve(
    name: Install,
    enabled: t.Optional[bool],
    no_update: bool,
):
    """Resolve any missing or outdated dependencies."""
    install = name

    installed = installed_mods(
        install.mod_folder, valid=True, blacklisted=invert(enabled)
    )
    installed = list(
        ProgressBar(installed, desc="Reading Installed Mods", leave=False, unit="")
    )
    installed_dict = {meta.Name: meta for meta in installed}

    deps, _opt_deps = resolve_dependencies(installed)

    _special, deps_installed, deps_missing = multi_partition(
        lambda meta: meta.Name in ("Celeste", "Everest"),
        lambda meta: meta.Name in installed_dict,
        iterable=deps,
    )

    deps_outdated = (
        [
            dep
            for dep in deps_installed
            if not installed_dict[dep.Name].Version.satisfies(dep.Version)
        ]
        if not no_update
        else []
    )

    if len(deps_missing) + len(deps_outdated) < 1:
        echo("No issues found.")
        return

    echo(
        f'{len(deps_missing) + len(deps_outdated)} dependencies missing{" or outdated" if len(deps_outdated) else ""}, attempting to resolve...'
    )

    # hand off to add mods command
    mons_cli.main(
        args=[
            "mods",
            "add",
            install.name,
            *[dep.Name for dep in itertools.chain(deps_missing, deps_outdated)],
        ]
    )
