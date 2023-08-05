import os
import sys
import typing as t
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import reload

import click
import pytest

from mons import config
from mons.install import Install


@pytest.fixture(autouse=True)
def isolated_filesystem(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Isolate all referenced files to temp folder"""
    user_dirs = ["config", "cache", "data"]
    ret = dict()
    for dir in user_dirs:
        monkeypatch.setattr(
            f"mons.config.PlatformDirs.user_{dir}_dir", os.path.join(tmp_path, dir)
        )
        ret[f"user_{dir}_dir"] = os.path.join(tmp_path, dir)
    # reload the config module to re-assign global constants
    reload(sys.modules["mons.config"])
    return ret


@pytest.fixture
def exception_count():
    @contextmanager
    def context(count):
        with pytest.raises(config.ExceptionCount) as exc_info:
            yield exc_info
        assert exc_info.value.count == count

    yield context


@dataclass(frozen=True)
class Subclass:
    subprop1: int = 321
    default: t.Optional[int] = None


@dataclass
class ConfigType:
    prop1: str

    subclass: Subclass = Subclass()


def test_dataclass_fromdict():
    test_config = config.dataclass_fromdict(
        {
            "prop1": "test",
        },
        ConfigType,
    )
    assert test_config == ConfigType("test")


def test_dataclass_fromdict_nested():
    test_config = config.dataclass_fromdict(
        {
            "prop1": "test",
            "subclass": {"subprop1": 123},
        },
        ConfigType,
    )
    assert test_config == ConfigType("test", Subclass(123, None))


@pytest.mark.parametrize(
    ("input, expect"),
    [
        ({"unknown": "test"}, (1, "Unknown key")),
        ({"prop1": 123}, (1, "Invalid value")),
        ({"prop1": {"invalid": "object"}}, (1, "Invalid value")),
        ({"subclass": 123}, (1, "Expected object")),
        ({"subclass": {"unknown": "key"}}, (1, "Unknown key")),
        (
            {"prop1": None, "subclass": {"unknown": "key", "subprop1": "invalid"}},
            (3, ""),
        ),
        ({}, (1, "Missing required key")),
    ],
    ids=lambda v: v[1] or f"{v[0]} errors" if isinstance(v, tuple) else None,
)
def test_dataclass_fromdict_errors(exception_count, caplog, input, expect):
    expect_count, expect_msg = expect
    with exception_count(expect_count):
        config.dataclass_fromdict(input, ConfigType)
    assert expect_msg in caplog.text


def test_wrap_config_param():
    @config.wrap_config_param
    def wrapped(cfg) -> None:
        assert isinstance(cfg, config.Config)

    wrapped(config.Config())
    wrapped(config.UserInfo())
    wrapped(click.Context(click.Command(None)))


# mons config-specific tests


def test_empty_config():
    assert config.dataclass_fromdict(
        {}, config.Config
    ), "All fields must have default values"


def test_save_data():
    assert not os.path.exists(config.INSTALLS_FILE)
    assert not os.path.exists(config.CACHE_FILE)

    with config.UserInfo() as user_info:
        user_info.installs["test_install"] = Install("test_install", "")  # type: ignore

    assert os.path.exists(config.INSTALLS_FILE)
    with open(config.INSTALLS_FILE) as file:
        assert "test_install:" in file.read()

    # install cache has not been updated, so should not be saved
    assert not os.path.exists(config.CACHE_FILE)


def test_save_cache():
    assert not os.path.exists(config.CACHE_FILE)

    with config.UserInfo() as user_info:
        install = Install("test_install", "")  # type: ignore
        # hash key specifically is checked to determine if install cache is valid
        install.get_cache().update(
            {
                "hash": "0123456789abcdef",
                "testkey": "testvalue",
            }
        )
        user_info.installs["test_install"] = install

    assert os.path.exists(config.CACHE_FILE)
    with open(config.CACHE_FILE) as file:
        assert "testkey: testvalue" in file.read()


def test_truncate_data():
    os.makedirs(config.CONFIG_DIR, exist_ok=True)
    assert not os.path.exists(config.INSTALLS_FILE)
    file_contents = """\
test_install:
    path: "fake/path"
other_install:
    path: "fake/path"
"""
    with open(config.INSTALLS_FILE, "w") as file:
        file.write(file_contents)

    # Data should not be truncated if not already loaded
    with config.UserInfo() as user_info:
        pass

    with open(config.INSTALLS_FILE) as file:
        assert file.read() == file_contents

    # Updated data should be saved to file
    with config.UserInfo() as user_info:
        del user_info.installs["other_install"]

    with open(config.INSTALLS_FILE) as file:
        assert "other_install" not in file

    # If all data removed, file should be truncated
    with config.UserInfo() as user_info:
        user_info.installs.clear()

    with open(config.INSTALLS_FILE) as file:
        assert not file.read()
