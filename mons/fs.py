import atexit
import os
import shutil
import sys
import tempfile
import typing as t
from contextlib import contextmanager

if sys.version_info < (3, 10):
    import typing_extensions as te
else:
    te = t

from mons.errors import silent_exec


class Path(str):
    def __new__(cls, *args, **kwargs):
        self = super().__new__(cls, *args, *kwargs)
        if not (os.path.isfile(self) or os.path.isdir(self)):
            raise FileNotFoundError
        return self


class File(Path):
    def __new__(cls, *args, **kwargs):
        self = str.__new__(cls, *args, **kwargs)
        if not os.path.isfile(self):
            raise FileNotFoundError
        return self


class Directory(Path):
    def __new__(cls, *args, **kwargs):
        self = str.__new__(cls, *args, **kwargs)
        if not os.path.isdir(self):
            raise FileNotFoundError
        return self


def isdir(path: str) -> te.TypeGuard[Directory]:
    return os.path.isdir(path)


def isfile(path: str) -> te.TypeGuard[File]:
    return os.path.isfile(path)


def joinfile(path: Directory, *paths: str):
    return File(os.path.join(path, *paths))


def joindir(path: Directory, *paths: str):
    return Directory(os.path.join(path, *paths))


def joinpath(path: Directory, *paths: str):
    return Path(os.path.join(path, *paths))


def find_file(path: Directory, files: t.Iterable[str]):
    """Return the first file in :param:`files` found in :param:`path`, or :literal:`None`."""
    for file in files:
        if isfile(os.path.join(path, file)):
            return file
    return None


def dirname(path: File):
    return Directory(os.path.dirname(path))


def folder_size(path: Directory):
    """Compute the size of a folder on disk as reported by :func:`os.stat`."""
    total_size = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = joinfile(Directory(dirpath), f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)

    return total_size


def is_unchanged(src: Path, dest: str):
    """Returns :literal:`True` if :param:`src` has not been changed after :param:`dest` was."""
    if os.path.exists(dest):
        return os.stat(dest).st_mtime - os.stat(src).st_mtime >= 0
    return False


@contextmanager
def relocated_file(src: File, dest: str):
    """Temporarily moves :param:`src` to :param:`dest`."""
    file = shutil.move(src, dest)
    try:
        yield file
    finally:
        shutil.move(file, src)


@contextmanager
def copied_file(src: File, dest: str):
    """Temporarily copies :param:`src` to :param:`dest`."""
    file = shutil.copy(src, dest)
    try:
        yield file
    finally:
        os.remove(file)


@contextmanager
def temporary_file(persist=False):
    fd, path = tempfile.mkstemp(suffix="_mons")
    if persist:
        atexit.register(silent_exec, os.remove, path)  # type: ignore
    os.close(fd)
    try:
        yield File(path)
    finally:
        if not persist and isfile(path):
            os.remove(path)
