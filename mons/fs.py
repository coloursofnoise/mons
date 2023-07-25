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


# shutils.copytree(dirs_exist_ok) replacement https://stackoverflow.com/a/15824216
def copy_recursive_force(
    src: Path,
    dest: str,
    *,
    filter: t.Optional[t.Callable[[Directory, t.List[str]], t.List[str]]] = None,
):
    """Recursively copies files from `src` to `dest`.

    :param src: Source file/directory path.
    :param dest: Destination path, will be created if it does not exist.
    :param filter: Filter files for each level of recursion.
    Takes the current directory and the list of children, and returns a filtered list of children.
    :raises OSError: If `src` is not a file or directory.
    :return: The number of files that were copied.
    """

    if isfile(src):
        shutil.copy2(src, dest)
        return 1

    if not isdir(src):
        raise NotADirectoryError(src)

    if not isdir(dest):
        os.makedirs(dest)

    files = os.listdir(src)
    files = filter(src, files) if filter else files

    return sum(
        copy_recursive_force(joinpath(src, f), os.path.join(dest, f), filter=filter)
        for f in files
    )


def copy_changed_files(
    src: Path,
    dest: str,
    *,
    filter: t.Optional[t.Callable[[Directory, t.List[str]], t.Iterable[str]]] = None,
):
    """Copies any files in `src` that do not exist in `dest` or are newer/more recently changed than their equivalent.

    :raises OSError: If `src` is not a file or directory.
    :return: The number of files that were copied.
    """

    def filter_changed(copy_source: Directory, filenames: t.List[str]):
        copy_dest = os.path.join(dest, os.path.relpath(copy_source, src))
        return [
            file
            for file in (filter(copy_source, filenames) if filter else filenames)
            if not is_unchanged(
                joinpath(copy_source, file), os.path.join(copy_dest, file)
            )
        ]

    return copy_recursive_force(
        src,
        dest,
        filter=filter_changed,
    )


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
