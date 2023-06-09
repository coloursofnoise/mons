import logging
import os
import shutil
import typing as t
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait
from contextlib import nullcontext
from http.client import HTTPResponse
from io import BytesIO
from tempfile import TemporaryDirectory
from urllib.error import URLError

import typing_extensions as te
import urllib3.util
from click import Abort
from urllib3.exceptions import HTTPError

from mons import baseUtils  # required to set module variable
from mons import fs
from mons.baseUtils import read_with_progress
from mons.modmeta import ModDownload
from mons.modmeta import UpdateInfo


logger = logging.getLogger(__name__)


def get_download_size(
    url: str, initial_size=0, http_pool: t.Optional[urllib3.PoolManager] = None
):
    parsed = urllib3.util.parse_url(url)
    if parsed.scheme == "file":
        return os.path.getsize(parsed.path or "")
    http = http_pool or urllib3.PoolManager()
    response = http.request("HEAD", url)
    return int(response.headers.get("Content-Length", initial_size)) - initial_size


@t.overload
def download_with_progress(
    src: t.Union[str, urllib.request.Request, HTTPResponse],
    dest: str,
    label: t.Optional[str] = ...,
    atomic: te.Literal[True] = ...,
    clear: bool = ...,
    *,
    response_handler: t.Optional[t.Callable[[HTTPResponse], HTTPResponse]] = ...,
    pool_manager: t.Optional[urllib3.PoolManager] = ...,
) -> None:
    ...


@t.overload
def download_with_progress(
    src: t.Union[str, urllib.request.Request, HTTPResponse],
    dest: None,
    label: t.Optional[str] = ...,
    atomic: te.Literal[False] = ...,
    clear: bool = ...,
    *,
    response_handler: t.Optional[t.Callable[[HTTPResponse], HTTPResponse]] = ...,
    pool_manager: t.Optional[urllib3.PoolManager] = ...,
) -> BytesIO:
    ...


@t.overload
def download_with_progress(
    src: t.Union[str, urllib.request.Request, HTTPResponse],
    dest: str,
    label: t.Optional[str] = ...,
    atomic: te.Literal[False] = ...,
    clear: bool = ...,
    *,
    response_handler: t.Optional[t.Callable[[HTTPResponse], HTTPResponse]] = ...,
    pool_manager: t.Optional[urllib3.PoolManager] = ...,
) -> None:
    ...


def download_with_progress(
    src: t.Union[str, urllib.request.Request, HTTPResponse],
    dest: t.Optional[str],
    label: t.Optional[str] = None,
    atomic=False,
    clear=False,
    *,
    response_handler: t.Optional[t.Callable[[HTTPResponse], HTTPResponse]] = None,
    pool_manager: t.Optional[urllib3.PoolManager] = None,
):
    if not dest and atomic:
        raise ValueError("atomic download cannot be used without destination file")

    http = pool_manager or urllib3.PoolManager()

    if isinstance(src, (str, urllib.request.Request)):
        try:
            response = t.cast(
                HTTPResponse,
                http.request(
                    "GET",
                    src,  # type: ignore
                    preload_content=False,
                    timeout=urllib3.Timeout(connect=3, read=10),
                ),
            )
        except HTTPError as e:
            try:
                # try to fallback to urlopen, notably for file:// scheme
                response = urllib.request.urlopen(src)
            except URLError:
                raise e
    else:
        response = src

    content = response_handler(response) if response_handler else response
    size = int(response.headers.get("Content-Length", None) or 100)
    blocksize = 8192

    if dest is None:
        io = BytesIO()
        read_with_progress(content, io, size, blocksize, label, clear)
        io.seek(0)
        return io

    with fs.temporary_file(persist=False) if atomic else nullcontext(dest) as file:
        with open(file, "wb") as io:
            read_with_progress(content, io, size, blocksize, label, clear)

        if atomic:
            if os.path.isfile(dest):
                os.remove(dest)
            shutil.move(file, dest)

    return None


def downloader(
    src: str,
    dest: str,
    name: str,
    mirror: t.Optional[str] = None,
    http_pool: t.Optional[urllib3.PoolManager] = None,
):
    mirror = mirror or src

    if os.path.isdir(dest):
        logger.warning(f"\nCould not overwrite unzipped mod: {os.path.basename(dest)}")
    try:
        download_with_progress(
            src, dest, f"{name} {src}", atomic=True, clear=True, pool_manager=http_pool
        )
    except Abort:
        return
    except Exception as e:
        logger.warning(f"\nError downloading file {os.path.basename(dest)} {src}: {e}")
        if isinstance(e, (HTTPError)) and src != mirror:
            downloader(mirror, dest, name)


def mod_downloader(
    mod_folder: fs.Directory,
    download: t.Union[ModDownload, UpdateInfo],
    http_pool: urllib3.PoolManager,
):
    dest = (
        download.Meta.Path
        if isinstance(download, UpdateInfo)
        else os.path.join(mod_folder, download.Meta.Name + ".zip")
    )
    downloader(download.Url, dest, str(download.Meta), download.Mirror, http_pool)


def download_threaded(
    mod_folder: fs.Directory,
    downloads: t.Sequence[t.Union[ModDownload, UpdateInfo]],
    late_downloads: t.Optional[t.Sequence[t.Union[ModDownload, UpdateInfo]]] = None,
    thread_count=8,
):
    http_pool = urllib3.PoolManager(maxsize=thread_count)
    with ThreadPoolExecutor(
        max_workers=thread_count, thread_name_prefix="download_"
    ) as pool:
        futures = [
            pool.submit(mod_downloader, mod_folder, download, http_pool)
            for download in downloads
        ]
        with TemporaryDirectory("_mons") if late_downloads else nullcontext(
            ""
        ) as temp_dir:
            if late_downloads:
                futures += [
                    pool.submit(
                        mod_downloader, fs.Directory(temp_dir), download, http_pool
                    )
                    for download in late_downloads
                ]
            try:
                while True:
                    _, not_done = wait(futures, timeout=0.1)
                    if len(not_done) < 1:
                        break
            except (KeyboardInterrupt, SystemExit):
                for future in futures:
                    future.cancel()
                baseUtils._download_interrupt = (  # pyright: ignore[reportPrivateUsage]
                    True
                )
                raise

            if late_downloads:
                for file in os.listdir(temp_dir):
                    if os.path.isfile(os.path.join(mod_folder, file)):
                        os.remove(os.path.join(mod_folder, file))
                    shutil.move(os.path.join(temp_dir, file), mod_folder)
