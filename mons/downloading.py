import os
import shutil
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.error import URLError

from tqdm import tqdm
from click import Abort

from .utils import ModDownload, UpdateInfo, download_with_progress, nullcontext
from . import utils

import typing as t

def downloader(src, dest, name, mirror=None):
    mirror = mirror or src

    if os.path.isdir(dest):
        tqdm.write(f'\nCould not overwrite unzipped mod: {os.path.basename(dest)}')
    try:
        download_with_progress(src, dest, f'{name} {src}', atomic=True, clear=True)
    except Abort:
        return
    except Exception as e:
        tqdm.write(f'\nError downloading file {os.path.basename(dest)} {src}: {e}')
        if isinstance(e, (TimeoutError, URLError)) and src != mirror:
            downloader(mirror, dest, name)

def mod_downloader(mod_folder, download:t.Union[ModDownload, UpdateInfo]):
    if isinstance(download, ModDownload):
        src, mirror, dest, name = download.Url, download.Mirror, os.path.join(mod_folder, download.Meta.Name + '.zip'), str(download.Meta)
    else:
        src, mirror, dest, name = download.Url, download.Mirror, download.Old.Path, str(download.Old)

    downloader(src, dest, name, mirror)

def download_threaded(mod_folder, downloads: t.Sequence[t.Union[ModDownload, UpdateInfo]], late_downloads=None, thread_count=8):
    with ThreadPoolExecutor(max_workers=thread_count, thread_name_prefix='download_') as pool:
        futures = [pool.submit(mod_downloader, mod_folder, download) for download in downloads]
        with TemporaryDirectory('_mons') if late_downloads else nullcontext('') as temp_dir:
            if late_downloads:
                futures += [pool.submit(mod_downloader, temp_dir, download) for download in late_downloads]
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
