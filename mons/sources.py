import os
import time
import typing as t
import urllib.parse
from functools import update_wrapper
from urllib.request import urlopen

import typing_extensions as te
import yaml
from click import Context

import mons.config as Defaults
from mons.config import CACHE_DIR
from mons.config import Config
from mons.config import UserInfo
from mons.downloading import download_with_progress

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
    except:
        return None


def write_cache(filename: str, data: t.Any, writer):
    filepath = os.path.join(CACHE_DIR, filename)
    try:
        with open(filepath, "w") as file:
            writer(data, file)
    except:
        # Don't leave partial caches
        os.remove(filepath)
        return


def cache_is_valid(filename, lifespan) -> bool:
    try:
        return time.time() - os.stat(os.path.join(CACHE_DIR, filename)).st_mtime < (
            lifespan * 60
        )
    except:
        return False


_MEM_CACHE = dict()


def with_cache(
    filename: str,
    *,
    lifespan=15,
    reader=yaml.safe_load,
    writer=yaml.safe_dump,
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


@with_cache("build_list.yaml")
@wrap_config_param
def fetch_build_list(config: Config) -> t.List[t.Dict[str, t.Any]]:
    download_url = (
        config.downloading.everest_builds
        or urlopen(Defaults.EVEREST_UPDATER).read().decode().strip()
    )

    return yaml.safe_load(
        download_with_progress(download_url, None, "Downloading Build List", clear=True)
    )


@with_cache("mod_database.yaml")
@wrap_config_param
def fetch_mod_db(config: Config) -> t.Dict[str, t.Any]:
    download_url = (
        config.downloading.mod_db
        or urlopen(Defaults.MOD_UPDATER).read().decode().strip()
    )

    return yaml.safe_load(
        download_with_progress(
            download_url,
            None,
            "Downloading Mod Database",
            clear=True,
        )
    )


@with_cache("dependency_graph.yaml")
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
    response = urlopen(url)
    return yaml.safe_load(response.read())


def fetch_random_map():
    url = urlopen(Defaults.RANDOM_MAP).url
    return url
