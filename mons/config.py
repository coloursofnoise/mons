import os
import shutil
import typing as t
from contextlib import AbstractContextManager
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import fields

import typing_extensions as te
import yaml
from click import ClickException
from click import make_pass_decorator
from platformdirs import PlatformDirs

from mons import fs
from mons.baseUtils import T
from mons.errors import EmptyFileError
from mons.errors import MultiException
from mons.install import Install

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
    @dataclass(frozen=True)
    class Downloading:
        # Marked optional because the default URL is just a text file with the actual URL in it.
        # Default: https://everestapi.github.io/everestupdater.txt
        everest_builds: t.Optional[str] = None
        # Default: https://everestapi.github.io/modupdater.txt
        mod_db: t.Optional[str] = None
        autobuild_repo: str = "EverestAPI/Everest"
        source_repo: str = "https://github.com/EverestAPI/Everest.git"
        thread_count: int = 8

    source_directory: t.Optional[str] = None
    build_args: t.List[str] = field(default_factory=list)
    default_install: t.Optional[str] = None
    launch_args: t.List[str] = field(default_factory=list)

    downloading: Downloading = Downloading()


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


def dataclass_fromdict(data: t.Dict[str, t.Any], type: t.Type[T]) -> T:
    type_fields = {f.name: f.type for f in fields(type) if f.init}
    errors: t.List[Exception] = list()
    for k, v in data.items():
        if k not in type_fields:
            errors.append(Exception(f"Unknown key: {k}"))
            continue

        # Retrieve type checkable version of generic and special types
        # Only checks base type, so 'List[str]' is only checked as 'list'
        checkable_type = te.get_origin(type_fields[k]) or type_fields[k]
        if not isinstance(v, checkable_type):
            if issubclass(type_fields[k], object):  # recursively deserialize objects
                try:
                    load_yaml(str(v), type_fields[k])
                except MultiException as e:
                    errors.extend(e.list)
                except Exception as e:
                    errors.append(e)
            else:
                errors.append(Exception(f"Invalid value for key {k}: {v}"))
    if len(errors) > 1:
        raise MultiException("", errors)
    if len(errors) == 1:
        raise errors[0]

    return type(**data)


_cache: t.Dict[str, t.Any] = dict()
_cache_loaded = False


def load_cache():
    global _cache_loaded
    _cache_loaded = True

    with open(CACHE_FILE) as file:
        data: t.Dict[str, t.Any] = yaml.safe_load(file)
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
                "everest_version": data["everest_version"],
            }
        )
        return True
    except KeyError:
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
            except (FileNotFoundError, EmptyFileError):
                self._config = Config()
            except MultiException as e:
                e.message = "Multiple errors loading config"
                raise ClickException(str(e))
            except Exception as e:
                raise ClickException("Error loading config:\n  " + str(e))

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
        if self._installs:
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

            cache_updates = {
                install.name: install.get_cache()
                for install in self._installs.values()
                if install.hash
            }
            if not _cache_loaded and cache_updates:
                load_cache()
            _cache.update(cache_updates)
            if not _cache:
                return

            with fs.temporary_file() as temp:
                with open(temp, "w") as file:
                    yaml.safe_dump(_cache, file)
                shutil.move(temp, CACHE_FILE)


pass_userinfo = make_pass_decorator(UserInfo)
pass_env = make_pass_decorator(Env, ensure=True)
