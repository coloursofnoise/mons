import os
import typing as t
from contextlib import AbstractContextManager
from dataclasses import dataclass
from dataclasses import fields

import click
import yaml

from mons.baseUtils import T
from mons.errors import EmptyFileError
from mons.errors import MultiException

config_dir = click.get_app_dir("mons", roaming=False)

CONFIG_FILE = os.path.join(config_dir, "config.yaml")


def get_default_install():
    return os.environ.get("MONS_DEFAULT_INSTALL", None)


@dataclass
class Env:
    skip_confirmation = False
    ignore_errors = False


@dataclass
class Config:
    @dataclass
    class Downloading:
        everest_builds: str = "https://everestapi.github.io/everestupdater.txt"
        mod_db: str = "https://everestapi.github.io/modupdater.txt"
        autobuild_repo: str = "EverestAPI/Everest"
        source_repo: str = "https://github.com/EverestAPI/Everest.git"
        thread_count: int = 8

    source_directory: t.Optional[str] = None
    default_install: t.Optional[str] = None

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

        elif not isinstance(v, type_fields[k]):
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


class UserInfo(AbstractContextManager):  # pyright: ignore[reportMissingTypeArgument]
    @property
    def config(self):
        try:
            if not self._config:
                self._config = read_yaml(CONFIG_FILE, Config)
        except (FileNotFoundError, EmptyFileError):
            self._config = Config()
        except MultiException as e:
            e.message = "Multiple errors loading config"
            raise click.ClickException(str(e))
        except Exception as e:
            raise click.ClickException("Error loading config:\n  " + str(e))

        return self._config

    _config: t.Optional[Config] = None

    def __enter__(self):
        return self

    def __exit__(self, *exec_details):
        pass


pass_userinfo = click.make_pass_decorator(UserInfo)
pass_env = click.make_pass_decorator(Env, ensure=True)
