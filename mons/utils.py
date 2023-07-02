import errno
import hashlib
import logging
import os
import time
import typing as t
import zipfile
from contextlib import contextmanager

import dnfile  # https://github.com/malwarefrank/dnfile
import typing_extensions as te
from pefile import (  # pyright:ignore[reportMissingTypeStubs]
    DIRECTORY_ENTRY,
)  # https://github.com/erocarrera/pefile

from mons import fs
from mons.baseUtils import GeneratorWithLen
from mons.logging import ProgressBar
from mons.modmeta import ModMeta
from mons.modmeta import read_mod_info
from mons.platforms import assert_platform
from mons.platforms import is_platform
from mons.version import NOVERSION
from mons.version import Version


logger = logging.getLogger(__name__)


VANILLA_HASH: t.Dict[str, t.Tuple[Version, te.Literal["FNA", "XNA"]]] = {
    "f1c4967fa8f1f113858327590e274b69": (Version(1, 4, 0, 0), "FNA"),
    "107cd146973f2c5ec9fb0b4f81c1588a": (Version(1, 4, 0, 0), "XNA"),
}


def find_celeste_asm(path: fs.Path):
    if fs.isfile(path):
        if os.path.basename(path) == "Celeste.exe":
            return path

        if (
            not (is_platform("Windows") and assert_platform("Windows"))
            and os.path.basename(path) == "Celeste.dll"
        ):
            return path

    elif fs.isdir(path):
        if os.path.basename(path) == "Celeste.app":
            path = fs.joindir(path, "Resources")

        if fs.isfile(os.path.join(path, "Celeste.exe")):
            return fs.joinfile(path, "Celeste.exe")

        if not (is_platform("Windows") and assert_platform("Windows")) and fs.isfile(
            os.path.join(path, "Celeste.dll")
        ):
            return fs.joinfile(path, "Celeste.dll")

    if is_platform("Windows") and assert_platform("Windows"):
        raise FileNotFoundError(errno.ENOENT, "'Celeste.exe' could not be found", path)
    raise FileNotFoundError(
        errno.ENOENT, "'Celeste.exe' or 'Celeste.dll' could not be found", path
    )


def getMD5Hash(path: fs.File):
    with open(path, "rb") as f:
        file_hash = hashlib.md5()
        chunk = f.read(8129)
        while chunk:
            file_hash.update(chunk)
            chunk = f.read(8129)
    return file_hash.hexdigest()


def unpack(zip: zipfile.ZipFile, root: fs.Directory, prefix="", label="Extracting"):
    totalSize = 0
    for zipinfo in zip.infolist():
        if not prefix or zipinfo.filename.startswith(prefix):
            totalSize += zipinfo.file_size

    with ProgressBar(total=totalSize, desc=label, leave=False) as bar:
        for zipinfo in zip.infolist():
            if not zipinfo.filename or zipinfo.filename.endswith("/"):
                continue

            if prefix:
                if not zipinfo.filename.startswith(prefix):
                    continue
                zipinfo.filename = zipinfo.filename[len(prefix) :]

            zip.extract(zipinfo, root)
            bar.update(zipinfo.file_size)


def parseExeInfo(path: fs.File):
    logger.info(f"Retrieving version information from {path}.")
    pe = dnfile.dnPE(path, fast_load=True)
    pe.parse_data_directories(
        directories=DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR"]
    )

    assert pe.net

    stringHeap: dnfile.stream.StringsHeap = pe.net.metadata.streams_list[1]  # type: ignore

    hasEverest = False
    everestBuild = None

    heapSize = stringHeap.sizeof()
    i = 0
    with ProgressBar(total=heapSize, desc="Scanning exe", leave=False) as bar:
        while i < len(stringHeap.__data__):
            string = stringHeap.get(i)
            if string is None:
                break
            string = str(string)
            if string == "EverestModule":
                logging.debug("Found EverestModule in string heap")
                hasEverest = True
            if string.startswith("EverestBuild"):
                everestBuild = string[len("EverestBuild") :]
                logging.debug(
                    "Found EverestBuild in string heap with suffix: " + everestBuild
                )
                hasEverest = True
                break
            inc = max(len(string), 1)
            i += inc
            bar.update(inc)

    assemRef = pe.net.mdtables.AssemblyRef
    assert assemRef
    framework = "FNA" if any(row.Name == "FNA" for row in assemRef.rows) else "XNA"

    if everestBuild:
        return Version(1, int(everestBuild), 0), framework
    if hasEverest:
        return NOVERSION(), framework

    return None, framework


def read_blacklist(path: fs.File):
    with open(path) as file:
        return [m.strip() for m in file.readlines() if not m.startswith("#")]


def installed_mods(
    path: fs.Directory,
    *,
    dirs: t.Optional[bool] = None,
    valid: t.Optional[bool] = None,
    blacklisted: t.Optional[bool] = None,
    folder_size=False,
    with_hash=False,
) -> t.Iterator[ModMeta]:
    files = os.listdir(path)
    blacklist = None
    if os.path.isfile(os.path.join(path, "blacklist.txt")):
        blacklist = read_blacklist(fs.joinfile(path, "blacklist.txt"))
        if blacklisted is not None:
            files = list(filter(lambda m: blacklisted ^ (m in blacklist), files))
    elif blacklisted:
        files = []

    def _iter():
        for file in files:
            modpath = fs.joinpath(path, file)
            if dirs is not None:
                if dirs ^ bool(fs.isdir(modpath)):
                    continue

            mod = read_mod_info(modpath, folder_size=folder_size, with_hash=with_hash)
            if valid is not None:
                if valid ^ bool(mod):
                    continue
            mod = mod or ModMeta.placeholder(modpath)
            if not mod:
                continue
            if blacklist and file in blacklist:
                mod.Blacklisted = True
            yield mod

    return GeneratorWithLen(_iter(), len(files))


def enable_mods(path: fs.Directory, *mods: str):
    blacklist_path = os.path.join(path, "blacklist.txt")
    if fs.isfile(blacklist_path):
        with open(blacklist_path) as file:
            blacklist = file.readlines()
        i = 0
        while i < len(blacklist):
            if blacklist[i].strip() in mods:
                blacklist[i] = "#" + blacklist[i]
            i += 1
        with open(blacklist_path, mode="w") as file:
            file.writelines(blacklist)
