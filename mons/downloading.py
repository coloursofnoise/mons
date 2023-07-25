import logging
import os
import re
import shutil
import sys
import typing as t
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait
from contextlib import nullcontext
from io import BytesIO
from tempfile import TemporaryDirectory
from urllib.error import URLError

import urllib3.util
from click import Abort
from urllib3.exceptions import HTTPError

from mons import baseUtils  # required to set module variable
from mons import fs
from mons.baseUtils import read_with_progress
from mons.modmeta import ModDownload
from mons.modmeta import UpdateInfo


logger = logging.getLogger(__name__)


_GB_URL_PATTERN = re.compile(r"^(https://gamebanana.com/(mm)?dl/.*),.*,.*$")


def parse_gb_dl(url) -> t.Optional[str]:
    """If `url` is a GameBanana download URL, strip the extraneous data if present.

    :returns: The GameBanana download URL, if found, otherwise `None`."""
    match = _GB_URL_PATTERN.match(url)
    return match[1] if match else None


class EverestHandler(urllib.request.BaseHandler):
    """everest:// scheme url handler"""

    def everest_open(self, req: urllib.request.Request):
        parsed_url = urllib.parse.urlparse(req.full_url)
        gb_url = parse_gb_dl(parsed_url.path)
        download_url = gb_url or parsed_url.path
        req.full_url = download_url
        return self.parent.open(req)


urllib.request.install_opener(urllib.request.build_opener(EverestHandler))


if sys.version_info >= (3, 8):  # novermin
    import importlib.metadata

    _version = importlib.metadata.version("mons")
else:
    import pkg_resources

    _version = pkg_resources.get_distribution("mons").version

_accepted_encodings = ["gzip", "deflate"]
_global_headers = {
    "User-Agent": f"mons/{_version}",
    "Accept-Encoding": ", ".join(_accepted_encodings),
}


class Download:
    def __init__(self, url: str, size: t.Optional[int] = None):
        self.url = url
        self.size = size and size


class URLResponse(t.Protocol):
    url: str
    headers: t.MutableMapping[str, str]

    def read(self, length=...) -> bytes:
        ...


@t.overload
def open_url(
    request: urllib.request.Request,
    *,
    pool_manager: t.Optional[urllib3.PoolManager] = ...,
) -> URLResponse:
    ...


@t.overload
def open_url(
    request: str,
    *,
    method: str = ...,
    headers: t.Optional[t.MutableMapping[str, str]] = ...,
    fields: t.Optional[t.MutableMapping[str, str]] = ...,
    pool_manager: t.Optional[urllib3.PoolManager] = ...,
) -> URLResponse:
    ...


def open_url(
    request: t.Union[str, urllib.request.Request],
    *,
    method="GET",
    headers: t.Optional[t.MutableMapping[str, str]] = None,
    fields: t.Optional[t.MutableMapping[str, str]] = None,
    pool_manager: t.Optional[urllib3.PoolManager] = None,
) -> URLResponse:
    """Send a request to a URL and return a generic response."""
    full_url = request if isinstance(request, str) else request.full_url
    if fields:
        full_url += "?" + urllib.parse.urlencode(fields)

    if headers:
        headers = {**_global_headers, **headers}

    try:
        http = pool_manager or urllib3.PoolManager()
        response = t.cast(
            URLResponse,
            http.request(
                method,
                t.cast(str, request),
                headers=headers,
                fields=fields,
                preload_content=False,
                timeout=urllib3.Timeout(connect=3, read=10),
            ),
        )
        response.url = full_url
        return response
    except HTTPError as e:
        try:
            logger.debug(f"HTTP Error from urllib3: {e}")
            logger.debug("Attempting to fall back on urlopen.")
            # try to fallback to urlopen, notably for file:// scheme
            if isinstance(request, str):
                if fields:
                    request += "?" + urllib.parse.urlencode(fields)
                request = urllib.request.Request(
                    request, headers=headers or {}, method=method
                )
            return urllib.request.urlopen(request)
        except URLError:
            raise e


def get_download_size(
    url: str, initial_size=0, http_pool: t.Optional[urllib3.PoolManager] = None
):
    parsed = urllib3.util.parse_url(url)
    if parsed.scheme == "file":
        return os.path.getsize(parsed.path or "")
    response = open_url(url, method="HEAD", pool_manager=http_pool)
    return int(response.headers.get("Content-Length", initial_size)) - initial_size


DownloadSource = t.Union[str, URLResponse, Download]
URLTransform = t.Callable[[URLResponse], URLResponse]


@t.overload
def download_with_progress(
    src: DownloadSource,
    dest: str,
    label: t.Optional[str] = ...,
    atomic: t.Literal[True] = ...,
    clear: bool = ...,
    *,
    response_handler: t.Optional[URLTransform] = ...,
    pool_manager: t.Optional[urllib3.PoolManager] = ...,
) -> None:
    ...


@t.overload
def download_with_progress(
    src: DownloadSource,
    dest: None,
    label: t.Optional[str] = ...,
    atomic: t.Literal[False] = ...,
    clear: bool = ...,
    *,
    response_handler: t.Optional[URLTransform] = ...,
    pool_manager: t.Optional[urllib3.PoolManager] = ...,
) -> BytesIO:
    ...


@t.overload
def download_with_progress(
    src: DownloadSource,
    dest: str,
    label: t.Optional[str] = ...,
    atomic: t.Literal[False] = ...,
    clear: bool = ...,
    *,
    response_handler: t.Optional[URLTransform] = ...,
    pool_manager: t.Optional[urllib3.PoolManager] = ...,
) -> None:
    ...


def download_with_progress(
    src: DownloadSource,
    dest: t.Optional[str],
    label: t.Optional[str] = None,
    atomic=False,
    clear=False,
    *,
    response_handler: t.Optional[URLTransform] = None,
    pool_manager: t.Optional[urllib3.PoolManager] = None,
):
    if not dest and atomic:
        raise ValueError("atomic download cannot be used without destination file")

    size = None
    if isinstance(src, Download):
        size = src.size
        src = src.url

    if isinstance(src, (str, urllib.request.Request)):
        response = open_url(src, pool_manager=pool_manager)
    else:
        response = src

    content = response_handler(response) if response_handler else response
    size = int(size or response.headers.get("Content-Length", None) or 100)
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
            logger.info("Attempting to download from mirror...")
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
    label = str(download.New_Meta if isinstance(download, UpdateInfo) else download)
    downloader(download.Url, dest, label, download.Mirror, http_pool)


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
