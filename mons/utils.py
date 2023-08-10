import hashlib
import logging
import os
import typing as t
import zipfile

from mons import fs
from mons.baseUtils import GeneratorWithLen
from mons.logging import ProgressBar
from mons.modmeta import ModMeta
from mons.modmeta import read_mod_info


logger = logging.getLogger(__name__)


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


def read_blacklist(path: fs.File):
    with open(path) as file:
        return [m.strip() for m in file.readlines() if not m.startswith("#")]


_MODS_FOLDER_IGNORE = ("Cache",)


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

            if not mod and file in _MODS_FOLDER_IGNORE:
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
