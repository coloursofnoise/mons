import os
import shutil
import typing as t
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait
from tempfile import TemporaryDirectory

import urllib3
from click import Abort
from tqdm import tqdm

from . import utils
from .utils import download_with_progress
from .utils import ModDownload
from .utils import nullcontext
from .utils import UpdateInfo


def downloader(src, dest, name, mirror=None, http_pool=None):
    mirror = mirror or src

    if os.path.isdir(dest):
        tqdm.write(f"\nCould not overwrite unzipped mod: {os.path.basename(dest)}")
    try:
        download_with_progress(
            src, dest, f"{name} {src}", atomic=True, clear=True, pool_manager=http_pool
        )
    except Abort:
        return
    except Exception as e:
        tqdm.write(f"\nError downloading file {os.path.basename(dest)} {src}: {e}")
        if isinstance(e, (urllib3.exceptions.HTTPError)) and src != mirror:
            downloader(mirror, dest, name)


def mod_downloader(mod_folder, download: t.Union[ModDownload, UpdateInfo], http_pool):
    if isinstance(download, ModDownload):
        src, mirror, dest, name = (
            download.Url,
            download.Mirror,
            os.path.join(mod_folder, download.Meta.Name + ".zip"),
            str(download.Meta),
        )
    else:
        src, mirror, dest, name = (
            download.Url,
            download.Mirror,
            download.Old.Path,
            str(download.Old),
        )

    downloader(src, dest, name, mirror, http_pool)


def download_threaded(
    mod_folder,
    downloads: t.Sequence[t.Union[ModDownload, UpdateInfo]],
    late_downloads=None,
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
                    pool.submit(mod_downloader, temp_dir, download, http_pool)
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
                utils._download_interrupt = True
                raise

            if late_downloads:
                for file in os.listdir(temp_dir):
                    shutil.move(os.path.join(temp_dir, file), mod_folder)
