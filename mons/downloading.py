import os
from typing import Sequence, Union
from concurrent.futures import ThreadPoolExecutor, wait

from tqdm import tqdm
from click import Abort

from .utils import ModDownload, UpdateInfo, download_with_progress
from . import utils

def downloader(mod_folder, download):
    if isinstance(download, ModDownload):
        src, dest, name = download.Url, os.path.join(mod_folder, download.Meta.Name + '.zip'), str(download.Meta)
    else:
        src, dest, name = download.Url, download.Old.Path, str(download.Old)
    label = f'{name} {src}'

    if os.path.isdir(dest):
        tqdm.write(f'\nCould not overwrite unzipped mod: {os.path.basename(dest)}')
    try:
        download_with_progress(src, dest, label, atomic=True, clear=True)
    except Abort:
        return
    except Exception as e:
        tqdm.write(f'\nError downloading file {os.path.basename(dest)}: {e}')

def download_threaded(mod_folder, downloads: Sequence[Union[ModDownload, UpdateInfo]], thread_count=8):
    with ThreadPoolExecutor(max_workers=thread_count, thread_name_prefix='download_') as pool:
        futures = [pool.submit(downloader, mod_folder, download) for download in downloads]
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
