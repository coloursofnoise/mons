import builtins
import logging
from unittest.mock import mock_open

import pytest

from mons import overlayfs
from mons.install import Install

# Only test this module on linux
pytestmark = pytest.mark.linux


def test_in_namespace(monkeypatch: pytest.MonkeyPatch):
    test_uid_map = "         0       1000          1\n"
    with monkeypatch.context() as m:
        m.setattr(builtins, "open", mock_open(read_data=test_uid_map))
        assert overlayfs.in_namespace()


@pytest.mark.xfail(reason="Fails if run from within a namespace", raises=AssertionError)
def test_not_in_namespace():
    assert not overlayfs.in_namespace()


OVERLAY_DIRS = overlayfs.OverlayDirs("lowerdir", "upperdir", "workdir", "mergeddir")


def ids_test_check_fstab(val):
    if isinstance(val, bool):
        return "found" if val else "notfound"
    input_markers = []
    val = val.strip()
    lines = val.split("\n")
    if "\n" in val:
        input_markers.append("multiline")
    checks = {
        "overlay": "overlayfs",
        "LABEL": "normalfs",
        "#": "comment",
    }
    input_markers += [
        marker
        for start, marker in checks.items()
        if any(line.startswith(start) for line in lines)
    ]
    if any(not line for line in lines):
        input_markers.append("emptyline")
    return "-".join(input_markers)


# Overlay dirs are assumed to be "lowerdir", "upperdir", "workdir", "mergeddir"
@pytest.mark.parametrize(
    ("data_file", "result"),
    [
        (
            "overlay mergeddir overlay lowerdir=lowerdir,upperdir=upperdir,workdir=workdir 0 0",
            True,
        ),
        (
            """
# This is an example /etc/fstab file containing an overlayfs entry

overlay mergeddir overlay lowerdir=lowerdir,upperdir=upperdir,workdir=workdir 0 0
""",
            True,
        ),
        (
            """
overlay mergeddir overlay lowerdir=lowerdir,upperdir=upperdir,workdir=somethingelse 0 0
overlay mergeddir overlay lowerdir=lowerdir,upperdir=upperdir,workdir=workdir 0 0
""",
            True,
        ),
        (
            """
# This is an example /etc/fstab file with multiple entries

# Regular fs
LABEL=MAIN / ext4 defaults 0 1
LABEL=SWAP none swap defaults 0 0

# Overlay fs
overlay mergeddir overlay lowerdir=lowerdir,upperdir=upperdir,workdir=workdir 0 0

# Regular fs
LABEL=HOME /home etx4 defaults 0 2
""",
            True,
        ),
        ("overlay mergeddir overlay default 0 0", False),
        ("overlay mergeddir overlay default", False),
        (
            "overlay mergeddir overlay lowerdir=lowerdir,upperdir=upperdir,workdir=somethingelse 0 0",
            False,
        ),
        pytest.param("overlay mergeddir overlay", ValueError, id="malformed-error"),
        ("", False),
        ("# Comment line", False),
        ("LABEL=SWAP none swap defaults 0 0", False),
    ],
    ids=ids_test_check_fstab,
    indirect=["data_file"],
)
def test_check_fstab(data_file, result):
    if isinstance(result, type) and issubclass(result, BaseException):
        with pytest.raises(result):
            overlayfs.check_fstab(OVERLAY_DIRS, fstab=data_file)
        return

    assert overlayfs.check_fstab(OVERLAY_DIRS, fstab=data_file) is result


def test_setup_is_mounted(monkeypatch, caplog, tmp_path, ctx):
    monkeypatch.setattr(overlayfs, "is_mounted", lambda *args: True)

    with caplog.at_level(logging.INFO, logger=overlayfs.__name__):
        overlayfs.setup(ctx, Install("test_setup_in_namespace", tmp_path, tmp_path))
        logs = [rec for rec in caplog.record_tuples if rec[0] == overlayfs.__name__]
        assert not logs


def test_setup_in_fstab(monkeypatch, caplog, tmp_path, ctx):
    monkeypatch.setattr(overlayfs, "is_mounted", lambda *args: False)
    monkeypatch.setattr(overlayfs, "check_fstab", lambda *args: True)

    with caplog.at_level(logging.INFO, logger=overlayfs.__name__):
        overlayfs.setup(ctx, Install("test_setup_in_namespace", tmp_path, tmp_path))
        logs = [rec for rec in caplog.record_tuples if rec[0] == overlayfs.__name__]
        assert not logs


def test_activate_is_mounted(monkeypatch, tmp_path):
    monkeypatch.setattr(overlayfs, "is_mounted", lambda *args: True)
