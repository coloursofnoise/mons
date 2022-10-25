from __future__ import annotations  # ABCs are not generic prior to 3.9

import os
import typing as t
from collections.abc import MutableMapping
from configparser import ConfigParser
from contextlib import AbstractContextManager
from dataclasses import dataclass

import click

from mons.install import Install


config_dir = click.get_app_dir("mons", roaming=False)

CONFIG_FILE = "config.ini"
INSTALLS_FILE = "installs.ini"
CACHE_FILE = "cache.ini"

# Config, Installs, Cache
Config_DEFAULT = {}
Install.DEFAULTS = {
    "PreferredBranch": "stable",
}


def get_default_install():
    return os.environ.get("MONS_DEFAULT_INSTALL", None)


@dataclass
class Env:
    skip_confirmation = False
    ignore_errors = False


def loadConfig(file: str, default: MutableMapping[str, str] = {}):
    config = ConfigParser()
    config_file = os.path.join(config_dir, file)
    if os.path.isfile(config_file):
        config.read(config_file)
    else:
        config["DEFAULT"] = default
        os.makedirs(config_dir, exist_ok=True)
        with open(config_file, "x") as f:
            config.write(f)
    return config


def saveConfig(config: ConfigParser, file: str):
    with open(os.path.join(config_dir, file), "w") as f:
        config.write(f)


def editConfig(config: ConfigParser, file: str):
    saveConfig(config, file)
    click.edit(
        filename=os.path.join(config_dir, file),
        editor=config.get("user", "editor", fallback=None),
    )
    return loadConfig(file, config["DEFAULT"])


class UserInfo(AbstractContextManager):  # pyright: ignore[reportMissingTypeArgument]
    def __enter__(self):
        self.config = loadConfig(CONFIG_FILE, Config_DEFAULT)
        installs = loadConfig(INSTALLS_FILE)
        cache = loadConfig(CACHE_FILE)

        def load_install(name: str):
            if not cache.has_section(name):
                cache.add_section(name)
            return Install(
                name, installs[name]["Path"], cache=cache[name], data=installs[name]
            )

        self.installs = {name: load_install(name) for name in installs.sections()}
        if not self.config.has_section("user"):
            self.config["user"] = {}
        return self

    def __exit__(self, *exec_details):
        saveConfig(self.config, CONFIG_FILE)
        installs = ConfigParser()
        cache = ConfigParser()
        for k, v in self.installs.items():
            installs[k] = v.serialize()
            cache[k] = v.cache
        saveConfig(installs, INSTALLS_FILE)
        saveConfig(cache, CACHE_FILE)


pass_userinfo = click.make_pass_decorator(UserInfo)
