import logging
import os
import shutil
import sys
import typing as t
from contextlib import AbstractContextManager
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import fields
from dataclasses import is_dataclass
from functools import update_wrapper

if sys.version_info < (3, 10):
    import typing_extensions as te
else:
    te = t
import yaml
from click import ClickException
from click import Context
from click import make_pass_decorator
from platformdirs import PlatformDirs

from mons import fs
from mons.baseUtils import T
from mons.errors import EmptyFileError
from mons.errors import ExceptionCount
from mons.install import Install

logger = logging.getLogger(__name__)

dirs = PlatformDirs("mons", False, ensure_exists=True)
CONFIG_DIR = dirs.user_config_dir
CACHE_DIR = dirs.user_cache_dir
DATA_DIR = dirs.user_data_dir

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")
INSTALLS_FILE = os.path.join(CONFIG_DIR, "installs.yaml")
CACHE_FILE = os.path.join(CACHE_DIR, "cache.yaml")


def get_default_install():
    return os.environ.get("MONS_DEFAULT_INSTALL", None)


@dataclass
class Env:
    skip_confirmation = False
    ignore_errors = False


# Defaults
CONTENT_URL = "https://everestapi.github.io"
EVEREST_UPDATER = f"{CONTENT_URL}/everestupdater.txt"
MOD_UPDATER = f"{CONTENT_URL}/modupdater.txt"

EXTRA_URL = "https://maddie480.ovh/celeste"
MOD_DEPENDENCY_GRAPH = f"{EXTRA_URL}/mod_dependency_graph.yaml"
MOD_SEARCH = f"{EXTRA_URL}/gamebanana-search"
RANDOM_MAP = f"{EXTRA_URL}/random-map"


@dataclass(frozen=True)
class Config:
    """The mons configuration file uses the YAML format."""

    @dataclass(frozen=True)
    class Downloading:
        everest_builds: t.Optional[str] = None
        """The URL used to fetch the list of Everest builds.

        By default, the URL is read from the contents of
        `https://everestapi.github.io/everestupdater.txt`.
        """

        mod_db: t.Optional[str] = None
        """The URL used to fetch the database of Everest-compatible mods.

        By default, the URL is read from the contents of
        `https://everestapi.github.io/modupdater.txt`.
        """

        autobuild_repo: str = "EverestAPI/Everest"  # TODO: unimplemented
        source_repo: str = (
            "https://github.com/EverestAPI/Everest.git"  # TODO: unimplemented
        )

        thread_count: int = 8
        """The maximum number of parallel downloads to use."""

    @dataclass(frozen=True)
    class OverlayFS:
        data_directory: t.Optional[str] = None
        """Used for the `upperdir` overlay mount option.

        Each install will have its own subdirectory within this folder, which
        will contain all files added or modified by this install.
        This directory should be writable.
        """

        work_directory: t.Optional[str] = None
        """Used for the `workdir` overlay mount option.

        Each install will have its own subdirectory within this folder, which
        will be wiped before each use.
        This directory should be writable, on the same filesystem as
        `data_directory`.
        """

    source_directory: t.Optional[str] = None
    """The default path to use when building Everest from source.

    Once set, this can still be overridden by providing a path from the
    commandline.
    """

    build_args: t.List[str] = field(default_factory=list)
    """Build options that are passed to `dotnet build` or `msbuild`.

    If the `dotnet` cli is not reliably available, both tools can accept
    `msbuild` options.

    See :manpage:`msbuild(1)` for available options.
    """

    default_install: t.Optional[str] = None  # TODO: unimplemented

    launch_args: t.List[str] = field(default_factory=list)
    """The default command-line arguments used when launching Celeste.

    Everest will also read arguments from the `everest-launch.txt` file. See
    Everest documentation for details.
    """

    downloading: Downloading = Downloading()
    """Options related to downloading files."""

    overlayfs: OverlayFS = OverlayFS()
    """Options pertaining to installs using an Overlay Filesystem (Linux only).

    See :doc:`mons-overlayfs(7) <overlayfs>` for information on overlayfs installs.
    """


def read_yaml(path: str, type: t.Type[T]) -> T:
    with open(path) as file:
        data = load_yaml(file, type)
    if not data:
        raise EmptyFileError(path)
    return data


def load_yaml(document: t.Any, type: t.Type[T]) -> t.Optional[T]:
    data: t.Dict[str, t.Any] = yaml.safe_load(document)
    if not data:
        return None

    return dataclass_fromdict(data, type)


def dataclass_fromdict(data: t.Dict[str, t.Any], field_type: t.Type[T]) -> T:
    type_fields = {f.name: f.type for f in fields(field_type) if f.init}
    errors = 0
    for k, v in data.items():
        if k not in type_fields:
            logger.error(f"Unknown key: '{k}'.")
            errors += 1
            continue
        # Retrieve type checkable version of generic and special types
        # Only checks base type, so 'List[str]' is only checked as 'list'
        checkable_type = t.get_origin(type_fields[k]) or type_fields[k]
        if checkable_type is t.Union:  # Optional type
            checkable_type = t.get_args(type_fields[k])
        if not isinstance(v, checkable_type):
            if isinstance(type_fields[k], type) and is_dataclass(
                type_fields[k]
            ):  # recursively deserialize objects
                try:
                    if not isinstance(v, dict):
                        logger.error(f"Expected object for key '{k}'.")
                        raise ExceptionCount(1)
                    data[k] = load_yaml(str(v), type_fields[k])
                except ExceptionCount as e:
                    errors += e.count
            else:
                logger.error(f"Invalid value for key '{k}': '{v}'.")
                errors += 1
    if errors:
        raise ExceptionCount(errors)

    try:
        return field_type(**data)
    except TypeError:
        import inspect

        required_args = [
            arg
            for arg in inspect.signature(field_type.__init__).parameters.values()
            if arg.default == inspect.Parameter.empty
        ]
        for arg in required_args:
            if arg.name != "self" and arg.name not in data:
                logger.error(f"Missing required key: '{arg.name}'")
                errors += 1
        if errors > 0:
            raise ExceptionCount(errors)
        raise  # In case the error comes from something else


_cache: t.Dict[str, t.Any] = dict()
_cache_loaded = False


def load_cache():
    global _cache_loaded
    _cache_loaded = True

    with open(CACHE_FILE) as file:
        data: t.Dict[str, t.Any] = yaml.safe_load(file)
        logger.debug(f"Cache loaded from '{CACHE_FILE}'.")
    if not data:
        raise EmptyFileError
    _cache.update(data)


def load_install_cache(install: Install):
    if install.name in _cache:
        return populate_cache(install, _cache[install.name])

    try:
        load_cache()
        if install.name in _cache:
            return populate_cache(install, _cache[install.name])
    except (FileNotFoundError, EmptyFileError):
        pass
    return False


def populate_cache(install: Install, data: t.Dict[str, t.Any]):
    try:
        install.get_cache().update(
            {
                "hash": data["hash"],
                "framework": data["framework"],
                "celeste_version": data["celeste_version"],
                "everest_version": data.get("everest_version", None),
            }
        )
        return True
    except KeyError as e:
        logger.error("KeyError populating cache: " + str(e))
        install.hash = None  # Invalidate cache
        return False


def install_repr(dumper: yaml.SafeDumper, o: Install):
    return dumper.represent_dict(
        {
            k: v
            for k, v in asdict(o).items()
            if not k.startswith("_") and not k == "name" and v
        }
    )


yaml.SafeDumper.add_representer(Install, install_repr)

yaml.SafeDumper.add_multi_representer(fs.Path, yaml.SafeDumper.represent_str)


class UserInfo(AbstractContextManager):  # pyright: ignore[reportMissingTypeArgument]
    _config: t.Optional[Config] = None
    _installs: t.Optional[t.Dict[str, Install]] = None

    @property
    def config(self):
        if not self._config:
            try:
                self._config = read_yaml(CONFIG_FILE, Config)
                logger.debug(f"User config loaded from '{CONFIG_FILE}'.")
            except (FileNotFoundError, EmptyFileError):
                self._config = Config()
            except ExceptionCount as e:
                raise ClickException(
                    f"{e.count} error(s) were encountered while loading config."
                )
            except yaml.error.YAMLError as e:
                raise ClickException(str(e))

        return self._config

    @property
    def installs(self):
        if not self._installs:
            try:
                with open(INSTALLS_FILE) as file:
                    data: t.Dict[str, t.Any] = yaml.safe_load(file)
                if not data:
                    raise EmptyFileError(INSTALLS_FILE)

                self._installs = {
                    k: Install(k, **v, _cache_loader=load_install_cache)
                    for (k, v) in data.items()
                }
                logger.debug(f"Install config loaded from '{INSTALLS_FILE}'.")
            except (FileNotFoundError, EmptyFileError):
                self._installs = dict()
            except Exception as e:
                msg = str(e)
                if isinstance(e, KeyError):
                    msg = f"Invalid install, missing {msg}"
                raise ClickException("Error loading config:\n  " + str(e))

        return self._installs

    def __enter__(self):
        return self

    def __exit__(self, *exec_details):
        if self._installs is None:
            return

        if len(self._installs) == 0:
            # clear install and cache files
            if os.path.exists(INSTALLS_FILE):
                with open(INSTALLS_FILE, "w"):
                    logger.debug(f"Truncated install config file '{INSTALLS_FILE}'.")
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, "w"):
                    logger.debug(f"Truncated cache file '{CACHE_FILE}'.")
            return

        # Use a temp file to avoid losing data if serialization fails
        with fs.temporary_file() as temp:
            with open(temp, "w") as file:
                yaml.safe_dump(
                    {install.name: install for install in self._installs.values()},
                    file,
                )
            # /tmp is very likely to be a tmpfs, os.rename/replace cannot handle cross-fs move
            os.makedirs(CONFIG_DIR, exist_ok=True)
            shutil.move(temp, INSTALLS_FILE)
            logger.debug(f"Install config saved to '{INSTALLS_FILE}'.")

        cache_updates = {
            install.name: install.get_cache()
            for install in self._installs.values()
            if install.hash
        }
        if not _cache_loaded and cache_updates:
            try:
                load_cache()
            except (OSError, EmptyFileError):
                pass
        _cache.update(cache_updates)
        if not _cache:
            return

        with fs.temporary_file() as temp:
            with open(temp, "w") as file:
                yaml.safe_dump(_cache, file)
            os.makedirs(CACHE_DIR, exist_ok=True)
            shutil.move(temp, CACHE_FILE)
            logger.debug(f"Cache saved to '{CACHE_FILE}'.")


pass_userinfo = make_pass_decorator(UserInfo)
pass_env = make_pass_decorator(Env, ensure=True)

P = te.ParamSpec("P")
R = t.TypeVar("R")


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
