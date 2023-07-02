import json
import os
import time
import typing as t
import urllib.parse
from functools import update_wrapper
from urllib.error import HTTPError

import typing_extensions as te
import yaml
from click import Context

import mons.config as Defaults
from mons.config import CACHE_DIR
from mons.config import Config
from mons.config import UserInfo
from mons.downloading import download_with_progress
from mons.downloading import open_url

P = te.ParamSpec("P")
R = te.TypeVar("R")


def wrap_config_param(
    f: t.Callable[te.Concatenate[Config, P], R]
) -> t.Callable[te.Concatenate[t.Union[Context, UserInfo, Config], P], R]:
    """Convenience wrapper to transform a passed Context or UserInfo into a Config"""

    def wrapper(config, *args: P.args, **kwargs: P.kwargs) -> R:
        if isinstance(config, Context):
            config = config.ensure_object(UserInfo)
        if isinstance(config, UserInfo):
            config = config.config
        return f(config, *args, **kwargs)

    return update_wrapper(wrapper, f)


def read_cache(filename: str, reader: t.Callable[[t.IO[t.Any]], t.Any]):
    try:
        with open(os.path.join(CACHE_DIR, filename)) as file:
            return reader(file)
    except Exception:
        return None


def write_cache(filename: str, data: t.Any, writer):
    filepath = os.path.join(CACHE_DIR, filename)
    try:
        with open(filepath, "w") as file:
            writer(data, file)
    except Exception:
        # Don't leave partial caches
        os.remove(filepath)
        return


def cache_is_valid(filename, lifespan) -> bool:
    try:
        return time.time() - os.stat(os.path.join(CACHE_DIR, filename)).st_mtime < (
            lifespan * 60
        )
    except Exception:
        return False


_MEM_CACHE = dict()


def with_cache(
    filename: str,
    *,
    lifespan=15,
    reader=json.load,
    writer=json.dump,
):
    """Wraps a function that returns a serializable object, and caches it in memory and on disk."""

    def decorator(fetch_func: t.Callable[P, R]) -> t.Callable[P, R]:
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            data = _MEM_CACHE.get(filename, None)
            if data:
                return data

            if cache_is_valid(filename, lifespan):
                data = read_cache(filename, reader)
            if not data:
                data = fetch_func(*args, **kwargs)
                write_cache(filename, data, writer)

            _MEM_CACHE[filename] = data
            return data

        return wrapper

    return decorator


@with_cache("build_list.json")
@wrap_config_param
def fetch_build_list(config: Config) -> t.List[t.Dict[str, t.Any]]:
    download_url = (
        config.downloading.everest_builds
        or open_url(Defaults.EVEREST_UPDATER).read().decode().strip()
    )

    return yaml.safe_load(
        download_with_progress(download_url, None, "Downloading Build List", clear=True)
    )


def fetch_latest_build(ctx, branch: str):
    if branch.startswith(("refs/heads/", "refs/pull/")):
        return fetch_latest_build_azure(branch)

    build_list = fetch_build_list(ctx)
    for build in build_list:
        if not branch or build["branch"] == branch:
            return int(build["version"])

    return None


def fetch_latest_build_azure(branch: str):
    response = open_url(
        "https://dev.azure.com/EverestAPI/Everest/_apis/build/builds",
        method="GET",
        fields={
            "definitions": "3",
            "statusFilter": "completed",
            "resultFilter": "succeeded",
            "branchName": branch
            if branch == "" or branch.startswith(("refs/heads/", "refs/pull/"))
            else "refs/heads/" + branch,
            "api-version": "6.0",
            "$top": "1",
        },
    )

    data: t.Dict[str, t.Any] = yaml.safe_load(response.read())
    if data["count"] < 1:
        return None
    elif data["count"] > 1:
        raise Exception("Unexpected number of builds: " + str(data["count"]))

    build = data["value"][0]
    id = build["id"]
    try:
        return int(id) + 700
    except ValueError:
        pass
    return None


def fetch_build_exists(ctx, build: int):
    build_list = fetch_build_list(ctx)
    if build in (int(b["version"]) for b in build_list):
        return True

    return fetch_build_exists_azure(build)


def fetch_build_exists_azure(build: int):
    try:
        open_url(
            "https://dev.azure.com/EverestAPI/Everest/_apis/build/builds/"
            + str(build - 700)
        )
        return True
    except HTTPError as err:
        if err.code == 404:
            return False
        raise


updateURLLookup = {
    "main": "mainDownload",
    "olympus-meta": "olympusMetaDownload",
    "olympus-build": "olympusBuildDownload",
}


def fetch_build_artifact(ctx, build: int, artifactName: str):
    build_list = fetch_build_list(ctx)
    for b in build_list:
        if build == int(b["version"]):
            return open_url(b[updateURLLookup[artifactName]], method="GET")

    return fetch_build_artifact_azure(build, artifactName)


def fetch_build_artifact_azure(build: int, artifactName="olympus-build"):
    return open_url(
        f"https://dev.azure.com/EverestAPI/Everest/_apis/build/builds/{build - 700}/artifacts",
        method="GET",
        fields={
            "artifactName": artifactName,
            "api-version": "6.0",
            "$format": "zip",
        },
    )


@with_cache("mod_database.json")
@wrap_config_param
def fetch_mod_db(config: Config) -> t.Dict[str, t.Any]:
    download_url = (
        config.downloading.mod_db
        or open_url(Defaults.MOD_UPDATER).read().decode().strip()
    )

    return yaml.safe_load(
        download_with_progress(
            download_url,
            None,
            "Downloading Mod Database",
            clear=True,
        )
    )


@with_cache("dependency_graph.json")
def fetch_dependency_graph() -> t.Dict[str, t.Any]:
    return yaml.safe_load(
        download_with_progress(
            Defaults.MOD_DEPENDENCY_GRAPH,
            None,
            "Downloading Dependency Graph",
            clear=True,
        )
    )


def fetch_mod_search(search: str):
    search = urllib.parse.quote_plus(search)
    url = f"{Defaults.MOD_SEARCH}?q={search}"
    response = open_url(url)
    return yaml.safe_load(response.read())


def fetch_random_map():
    url = open_url(Defaults.RANDOM_MAP).url
    return url
