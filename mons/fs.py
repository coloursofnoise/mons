import atexit
import os
import shutil
import tempfile
import typing as t
from contextlib import contextmanager

from mons.baseUtils import tryExec


def find_file(path: str, files: t.Iterable[str]):
    for file in files:
        if os.path.isfile(os.path.join(path, file)):
            return file
    return None


# shutils.copytree(dirs_exist_ok) replacement https://stackoverflow.com/a/15824216
def copy_recursive_force(src: str, dest: str, ignore=None):
    if os.path.isdir(src):
        if not os.path.isdir(dest):
            os.makedirs(dest)
        files = os.listdir(src)
        if ignore is not None:
            ignored = ignore(src, files)
        else:
            ignored: t.Collection[str] = set()
        for f in files:
            if f not in ignored:
                copy_recursive_force(
                    os.path.join(src, f), os.path.join(dest, f), ignore
                )
    else:
        shutil.copyfile(src, dest)


def folder_size(start_path="."):
    total_size = 0
    for dirpath, _, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)

    return total_size


def isUnchanged(src: str, dest: str, file: str):
    srcFile = os.path.join(src, file)
    destFile = os.path.join(dest, file)
    if os.path.exists(destFile):
        return os.stat(destFile).st_mtime - os.stat(srcFile).st_mtime >= 0
    return False


@contextmanager
def relocated_file(src: str, dest: str):
    file = shutil.move(src, dest)
    try:
        yield file
    finally:
        shutil.move(file, src)


@contextmanager
def copied_file(src: str, dest: str):
    file = shutil.copy(src, dest)
    try:
        yield file
    finally:
        os.remove(file)


@contextmanager
def temporary_file(persist=False):
    fd, path = tempfile.mkstemp(suffix="_mons")
    if persist:
        atexit.register(tryExec, os.remove, path)
    os.close(fd)
    try:
        yield path
    finally:
        if not persist and os.path.isfile(path):
            os.remove(path)
