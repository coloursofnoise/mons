import atexit
import os
import shutil
import tempfile
import typing as t
from contextlib import contextmanager

from mons.baseUtils import tryExec


def find_file(path: str, files: t.Iterable[str]):
    """Return the first file in :param:`files` found in :param:`path`, or :literal:`None`."""
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


def folder_size(path):
    """Compute the size of a folder on disk as reported by :func:`os.stat`."""
    total_size = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)

    return total_size


def is_unchanged(src: str, dest: str):
    """Returns :literal:`True` if :param:`src` has not been changed after :param:`dest` was."""
    if os.path.exists(dest):
        return os.stat(dest).st_mtime - os.stat(src).st_mtime >= 0
    return False


@contextmanager
def relocated_file(src: str, dest: str):
    """Temporarily moves :param:`src` to :param:`dest`."""
    file = shutil.move(src, dest)
    try:
        yield file
    finally:
        shutil.move(file, src)


@contextmanager
def copied_file(src: str, dest: str):
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
        atexit.register(tryExec, os.remove, path)
    os.close(fd)
    try:
        yield path
    finally:
        if not persist and os.path.isfile(path):
            os.remove(path)
