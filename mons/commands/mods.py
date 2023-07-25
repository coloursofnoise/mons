import itertools
import logging
import os
import re
import shutil
import typing as t
import urllib.parse
import urllib.request
from gettext import ngettext as _n
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
from mons.config import Env
from mons.config import UserInfo
from mons.downloading import download_threaded
from mons.downloading import download_with_progress
from mons.downloading import get_download_size
from mons.downloading import parse_gb_dl
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
from mons.sources import fetch_gb_downloads
from mons.sources import fetch_mod_db
from mons.sources import fetch_mod_search
from mons.sources import fetch_random_map
from mons.spec import MODSPEC
from mons.utils import enable_mods
from mons.utils import installed_mods
from mons.utils import read_blacklist
from mons.version import Version


logger = logging.getLogger(__name__)


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


def search_mods(ctx, search):
    search_regex = re.compile(".*".join(list(search)), re.IGNORECASE)
    api_matches = {
        result["GameBananaId"]: result for result in fetch_mod_search(search)
    }
    mod_db = fetch_mod_db(ctx)

    # Find matches, ordered by relevance
    partitions = multi_partition(
        lambda mod: mod == search,
        lambda mod: mod.lower() == search.lower(),
        lambda mod: mod.lower().startswith(search.lower()),
        lambda mod: search.lower() in mod.lower(),
        lambda mod: search_regex.search(mod) is not None,
        lambda mod: mod_db[mod]["GameBananaId"] in api_matches,
        iterable=mod_db.keys(),
    )[
        :-1
    ]  # discard remainder

    # Sort each tier of relevance
    for p in partitions:
        p.sort()

    return [ModMeta({"Name": mod, **mod_db[mod]}) for p in partitions for mod in p]


@cli.command(no_args_is_help=True)
@click.argument("search", nargs=-1, required=True)
# @click.option("-r", "--results", metavar="COUNT", default=None, type=click.INT, help="Number of results to show (default all).")
@click.option("-v", "--verbose", is_flag=True, help="Print mod details.")
@click.pass_context
def search(ctx, search: t.Tuple[str], verbose: bool):
    """Search the mod database."""
    search_str = " ".join(search)
    matches = search_mods(ctx, search_str)

    def format_line(meta: ModMeta):
        return click.style(
            f"{meta.Name} {click.style(meta.Version, fg='green')}\n", bold=True
        )  # + meta.Description

    def format_verbose(meta: ModMeta):
        formatted = format_mod(meta).splitlines()
        formatted[0] = click.style(formatted[0], bold=True)
        return "\n".join(formatted) + "\n" * 2

    formatter = format_verbose if verbose else format_line

    if matches:
        clickExt.echo_via_pager(map(formatter, matches))


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
    errors = 0
    mod_list = fetch_mod_db(ctx)
    dep_db = fetch_dependency_graph()

    def prompt_selection(matches, notice):
        if len(matches) == 1:
            return matches[0]

        echo(notice)
        for i, m in enumerate(matches):
            echo(f"  {i+1} {m}")
        return matches[
            click.prompt("Select one", type=click.IntRange(1, len(matches))) - 1
        ]

    for mod in mods:
        logger.debug(f"Resolving mod: {mod}")
        parsed_url = urllib.parse.urlparse(mod)

        # Everest 1-Click install links should just contain another URL as the path
        if parsed_url.scheme == "everest":
            gb_url = parse_gb_dl(parsed_url.path) or parsed_url.path
            parsed_url = urllib.parse.urlparse(gb_url)
            mod = gb_url
            logger.debug(f"Everest 1-Click URL, now resolving as {mod}.")

        # Direct URL match in mod database
        matches: t.List[ModDownload] = [
            ModDownload(
                ModMeta({"Name": key, **val, **dep_db[key]}),
                val["URL"],
                val["MirrorURL"],
            )
            for key, val in mod_list.items()
            if mod == val["URL"]
        ]
        if matches:
            logger.debug(f"{len(matches)} URL match(es) found in mod db.")
            resolved.append(
                prompt_selection(
                    matches, f"Multiple database matches found for URL '{mod}':"
                )
            )
            continue

        # Local filesystem
        if os.path.exists(mod):
            if os.path.splitext(mod)[1] == ".zip":
                logger.debug("Zip archive exists in filesystem.")
                parsed_url = urllib.parse.ParseResult(
                    "file", "", os.path.abspath(mod), "", "", ""
                )
                meta = read_mod_info(parsed_url.path)
                if meta:
                    resolved.append(
                        ModDownload(
                            meta,
                            urllib.parse.urlunparse(parsed_url),
                        )
                    )
                else:
                    unresolved.append(parsed_url.path)
                continue
            else:
                logger.error(f"Path '{mod}' is not a .zip archive.")
                errors += 1

        # Mod ID match
        if mod in mod_list:
            logger.debug("Mod name match found in mod db")
            mod_info = mod_list[mod]
            resolved.append(
                ModDownload(
                    ModMeta({"Name": mod, **mod_info, **dep_db[mod]}),
                    mod_info["URL"],
                    mod_info["MirrorURL"],
                )
            )
            continue

        # GameBanana submission URL
        if (
            parsed_url.scheme in ("http", "https")
            and parsed_url.netloc == "gamebanana.com"
            and parsed_url.path.startswith("/mods")
            and parsed_url.path.split("/")[-1].isdigit()
        ):
            mod_id = int(parsed_url.path.split("/")[-1])
            matches: t.List[ModDownload] = [
                ModDownload(
                    ModMeta({"Name": key, **val, **dep_db[key]}),
                    val["URL"],
                    val["MirrorURL"],
                )
                for key, val in mod_list.items()
                if mod_id == val["GameBananaId"]
            ]
            if len(matches) > 0:
                logger.debug(f"{len(matches)} GameBananaId match(es) found in mod db.")
                resolved.append(
                    prompt_selection(
                        matches,
                        f"Multiple database matches found for GameBanana ID '{mod_id}':",
                    )
                )
                continue

            submission = fetch_gb_downloads(mod_id)
            downloads = {
                d["_sFile"] + (d["_sDescription"] and f' ({d["_sDescription"]})'): d
                for d in submission["_aFiles"]
            }
            if len(downloads) > 0:
                logger.debug(
                    f"{len(downloads)} File downloads found on GameBanana page."
                )
                selection = prompt_selection(
                    list(downloads.keys()),
                    f"Multiple downloads available for mod '{submission['_sName']}':",
                )
                unresolved.append(downloads[selection]["_sDownloadUrl"])
                continue

        # Google Drive share URL
        if (
            parsed_url.scheme in ("http", "https")
            and parsed_url.netloc == "drive.google.com"
            and parsed_url.path.startswith("/file/d/")
        ):
            file_id = parsed_url.path[len("/file/d/") :].split("/")[0]
            url = "https://drive.google.com/uc?export=download&id=" + file_id
            unresolved.append(url)
            logger.debug(
                f"Mod is a valid google drive URl, direct download URL is {url}."
            )
            continue

        if parsed_url.scheme and parsed_url.path:
            logger.debug("Mod is a valid URL.")
            unresolved.append(mod)
            continue

        # Possible GameBanana Submission ID
        if mod.isdigit():
            mod_id = int(mod)
            matches = [
                ModDownload(
                    ModMeta({"Name": key, **val, **dep_db[key]}),
                    val["URL"],
                    val["MirrorURL"],
                )
                for key, val in mod_list.items()
                if mod_id == val["GameBananaId"]
            ]
            if matches:
                logger.debug(f"{len(matches)} GameBananaId match(es) found in mod db.")
                resolved.append(
                    prompt_selection(
                        matches,
                        f"Multiple database matches found for GameBanana ID '{mod_id}':",
                    )
                )
                continue

        logger.error(f"Mod '{mod}' could not be resolved and is not a valid URL.")
        errors += 1

    if errors > 0:
        logger.error(
            _n(
                "Encountered an error while resolving mods.",
                "Encountered {error_count} errors while resolving mods.",
                errors,
            ).format(error_count=errors)
        )
        if errors == len(mods) or not clickExt.confirm_ext(
            "Continue anyways?", default=False, dangerous=True
        ):
            raise click.Abort()
    return resolved, unresolved


def update_everest(install: Install, required: Version):
    current = install.everest_version
    if current and current.satisfies(required):
        return

    logger.warning(
        f"Installed Everest ({current}) does not satisfy minimum requirement ({required})."
    )
    if clickExt.confirm_ext("Update Everest?", default=True):
        mons_cli.main(args=["install", install.name, str(required)])


@cli.command(
    no_args_is_help=True,
    cls=clickExt.CommandExt,
    usages=[
        ["NAME", f"{MODSPEC}..."],
        ["NAME", "-"],
        ["NAME", "--search SEARCH..."],
        ["NAME", "--random"],
    ],
)
@clickExt.install("install", metavar="NAME", require_everest=True)
@click.argument("mods", nargs=-1)
@click.option(
    "--search",
    metavar="SEARCH...",
    is_flag=True,
    help="Use the Celeste mod search API to find a mod.",
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

    :term:`MODSPEC` can be one or more of: mod ID, local zip, zip URL, 1-Click install link, Google Drive share link, GameBanana page, or GameBanana submission ID.

    If '-' is the only argument provided, data for a mod zip will be read from stdin.
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
        # Query mod search API
        matches = search_mods(ctx, " ".join(mods))
        selections = clickExt.prompt_selections(
            matches,
            "Mods to install",
            reverse=True,
            find_index=lambda n: next(
                (i for i, m in enumerate(matches) if m.Name == n), None
            ),
        )
        mod_db = fetch_mod_db(ctx)
        dep_db = fetch_dependency_graph()
        # TODO: streamline initializing ModDownload with dependencies
        selections = [matches[i] for i in selections]
        resolved = [
            ModDownload(
                ModMeta({"Name": mod.Name, **mod_db[mod.Name], **dep_db[mod.Name]}),
                mod_db[mod.Name]["URL"],
                mod_db[mod.Name]["MirrorURL"],
            )
            for mod in selections
        ]
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
            echo(f"  {s}")

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

    # Remove duplicates
    resolved = list({m.Meta.Name: m for m in resolved}.values())

    deps, _opt_deps = (
        resolve_dependencies([mod.Meta for mod in resolved])
        if not no_deps
        else ([], [])
    )

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
        logger.warning("Unzipped mods will not be updated:")
        for update in skip_updates:
            logger.warning("  " + str(update))
    del skip_updates

    reinstall, resolved_update = partition(
        lambda u: u.New == u.Meta.Version, resolved_update
    )
    reinstall = [ModDownload(u.Meta, u.Url, u.Mirror) for u in reinstall]
    reinstall_str = (str(m.Meta) + " (reinstall)" for m in reinstall)

    install_count = len(resolved) + len(deps_install) + len(reinstall)
    if install_count > 0:
        echo(
            _n(
                "{install_count} mod to install:",
                "{install_count} mods to install:",
                install_count,
            ).format(install_count=install_count)
        )
        for download in sorted(
            itertools.chain(resolved, deps_install, reinstall_str), key=str
        ):
            echo("  " + str(download))
    update_count = len(resolved_update) + len(deps_update)
    if update_count > 0:
        echo(
            _n(
                "{update_count} mod to update:",
                "{update_count} mods to update:",
                update_count,
            ).format(update_count=update_count)
        )
        for update in sorted(itertools.chain(resolved_update, deps_update), key=str):
            echo("  " + str(update))

    if install_count + update_count < 1:
        echo("No mods to install.")
        return

    resolved += reinstall
    sorted_main_downloads = sorted(
        itertools.chain(resolved, resolved_update), key=attrgetter("Size")
    )
    sorted_dep_downloads = sorted(
        itertools.chain(deps_install, deps_update), key=attrgetter("Size")
    )

    download_size = sum(
        mod.Size
        for mod in itertools.chain(resolved, resolved_update, deps_install, deps_update)
        if mod not in reinstall
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
    ), "Not all mods were installed."

    blacklisted = [
        installed[mod.Meta.Name]
        for mod in itertools.chain(resolved, resolved_update, deps_install, deps_update)
        if installed[mod.Meta.Name].Blacklisted
    ]
    if blacklisted:
        logger.info(
            "The following mods will be automatically removed from the blacklist:"
        )
        logger.info(" ".join([str(mod) for mod in blacklisted]))
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
        logger.warning(
            "The following mods could not be found, and will not be removed:"
        )
        for mod in unresolved:
            logger.warning(f"{mod}")
        if not clickExt.confirm_ext("Continue anyways?", default=False, dangerous=True):
            raise click.Abort()

    metas = [installed_list[mod] for mod in resolved]

    if len(metas) < 1:
        echo("No mods to remove.")
        return

    echo(
        _n(
            "{len_remove} mod will be removed:",
            "{len_remove} mods will be removed:",
            len(metas),
        ).format(len_remove=len(metas))
    )
    for mod in metas:
        echo(f"  {mod}")

    removable_deps = (
        resolve_exclusive_dependencies(metas, installed_list) if recurse else []
    )
    if removable_deps:
        echo(
            _n(
                "{len_deps} dependency will also be removed:",
                "{len_deps} dependencies will also be removed:",
                len(removable_deps),
            ).format(len_deps=len(removable_deps))
        )
        for dep in removable_deps:
            echo(f"  {dep}")

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
        logger.warning("The following unzipped mods were not removed:")
        for mod in folders:
            logger.warning(f"  {mod} ({os.path.basename(mod.Path)}/)")


@cli.command(no_args_is_help=True, cls=clickExt.CommandExt)
@clickExt.install("name", require_everest=True)
# @click.argument('mod', required=False)
@click.option(
    "--enabled/--disabled",
    is_flag=True,
    help="Update currently enabled/disabled mods.",
    default=None,
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
                        server["MirrorURL"],
                        server["Size"],
                    )
                )

    if not updates:
        echo("All mods up to date")
        return

    updates.sort(key=str)

    if not ctx.ensure_object(Env).skip_confirmation:
        exclude = clickExt.prompt_selections(
            updates,
            message="Mods to exclude",
            find_index=lambda n: next(
                (i for i, m in enumerate(updates) if m.Meta.Name == n), None
            ),
        )
        if exclude:
            updates = [update for i, update in enumerate(updates) if i not in exclude]

    echo(
        _n(
            "{len_mods} mod will be updated:",
            "{len_mods} mods will be updated:",
            len(updates),
        ).format(len_mods=len(updates))
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
    "--enabled/--disabled",
    is_flag=True,
    help="Resolve currently enabled/disabled mods.",
    default=None,
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

    msg = _n(
        "{resolve_count} dependency missing",
        "{resolve_count} dependencies missing",
        len(deps_missing) + len(deps_outdated),
    ).format(len(deps_missing) + len(deps_outdated))
    if deps_outdated:
        msg += " or outdated"
    echo(msg)

    # hand off to add mods command
    mons_cli.main(
        args=[
            "mods",
            "add",
            install.name,
            *[dep.Name for dep in itertools.chain(deps_missing, deps_outdated)],
        ]
    )
