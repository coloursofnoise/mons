"""
# FOREWORD:

## User Namespaces
`unshare` (and the 'user'/'users' mount options?) rely on unpriviledged user
namespaces, which are disabled manually or by default on many systems due to
security concerns. They require a kernel configured with the CONFIG_USER_NS
and CONFIG_USER_NS_UNPRIVILEGED(Arch Linux only?) options.

While not present in the mainline kernel, some systems also have `sysctl`
options that can disable it again:
  kernel.unprivileged_userns_clone=0 (deprecated)
  user.max_user_namespaces=0

https://man.archlinux.org/man/user_namespaces.7.en#Availability
https://www.debian.org/releases/bullseye/amd64/release-notes/ch-information.en.html#linux-user-namespaces
"""
import logging
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import typing as t
from datetime import datetime

import click

from mons import clickExt
from mons import fs
from mons.baseUtils import partition
from mons.config import CACHE_DIR
from mons.config import DATA_DIR
from mons.config import wrap_config_param
from mons.errors import try_exec
from mons.formatting import ANSITextWrapper
from mons.install import Install


logger = logging.getLogger(__name__)


class OverlayDirs(t.NamedTuple):
    lowerdir: str
    upperdir: str
    workdir: str
    mergeddir: str


@wrap_config_param
def get_overlaydirs(config, install: Install):
    assert install.overlay_base, "Install does not have an overlay base."
    return OverlayDirs(
        lowerdir=install.overlay_base,
        upperdir=os.path.join(
            config.overlayfs.data_directory or os.path.join(DATA_DIR, "overlayfs"),
            install.name,
        ),
        workdir=os.path.join(
            config.overlayfs.work_directory or os.path.join(CACHE_DIR, "overlayfs"),
            install.name,
        ),
        mergeddir=install.path,
    )


def build_mount_options(lowerdir: str, upperdir: str, workdir: str, fstab=True):
    opts = [
        # Allow any user to mount and to unmount the filesystem
        "users",
        # Undo implicit 'noexec' applied by 'users'
        "exec",
        # Disable "inodes index" feature.
        # Fixes issues when mounting and re-mounting, but breaks hard-links
        "index=off",
        "lowerdir={}".format(lowerdir),
        "upperdir={}".format(upperdir),
        "workdir={}".format(workdir),
    ]
    if fstab:
        opts = [
            # Don't mount automatically during boot
            "noauto",
            # Automount when first accessed (should override noauto)
            "x-systemd.automount",
        ] + opts
    return ",".join(opts)


def build_fstab_entry(overlay_dirs: OverlayDirs):
    return " ".join(
        [
            "overlay",
            overlay_dirs.mergeddir,
            "overlay",
            build_mount_options(*overlay_dirs[:3]),
            "0",
            "0",
        ]
    )


def build_fstab_comment():
    return "# Added by mons " + datetime.now().date().isoformat()


def check_fstab(overlay_dirs: OverlayDirs, *, fstab="/etc/fstab"):
    lowerdir, upperdir, workdir, mergeddir = overlay_dirs
    with open(fstab) as file:
        for line in file.readlines():
            if line.startswith("#") or not line.strip():
                continue
            # fstab record fields 5-6 are optional, but should not be checked anyways.
            [fs_spec, fs_file, fs_vfstype, fs_mntops] = line.split()[:4]
            if (fs_spec == fs_vfstype == "overlay") and fs_file == mergeddir:
                opts = fs_mntops.split(",")
                if all(
                    o in opts
                    for o in [
                        "lowerdir={}".format(lowerdir),
                        "upperdir={}".format(upperdir),
                        "workdir={}".format(workdir),
                    ]
                ):
                    return True
    return False


@try_exec(
    exception_type=IOError, on_failure=Exception("Unable to determine mount state")
)
def is_mounted(overlay_dirs: OverlayDirs):
    if os.path.ismount(overlay_dirs.mergeddir):
        mount_file = "/proc/mounts"
        if not fs.isfile(mount_file):
            # Usually contain the same information (and are often symlinked)
            # but /proc/mounts is more likely to be up to date.
            mount_file = "/etc/mtab"
            assert fs.isfile(mount_file), "/etc/mtab does not exist."
        return check_fstab(overlay_dirs, fstab=mount_file)
    return False


@try_exec(exception_type=IOError, on_failure=False)
def in_namespace():
    with open("/proc/self/uid_map") as file:
        uid_map = file.read()
        # This will always be the value given for the "default" (nonexistant) namespace
        return uid_map.strip("\n") != "         0          0 4294967295"


ABOUT = """\
{sphinx_description}\
An Overlay Filesystem allows the contents of one directory to be overlaid on \
top of another. This means that Everest can be installed without modifying the \
base Celeste install, and without needing a second copy of Celeste.

Mounting a filesystem on linux usually requires superuser permissions, which \
would require entering the root password after every reboot. This is rather \
cumbersome, so a good alternative is to add an entry to '/etc/fstab' for the \
mount point. With the 'x-systemd.automount' option provided by systemd, the \
filesystem will only be mounted when it is accessed.

.. seealso:: :manpage:`mount(8)`, :manpage:`fstab(5)`, :manpage:`systemd.automount(5)`


If an overlay cannot be mounted without superuser permissions, an attempt will \
first be made to use an Unprivileged User Namespace. This can be used to \
create a container that has superuser privileges that are still isolated from \
the rest of the system.

.. seealso:: :manpage:`user_namespaces(7)`, :doc:`mons(1) <everest>`
{sphinx_end}\
""".format(
    sphinx_description="", sphinx_end=""
)


@wrap_config_param
def setup(config, install: Install):
    overlay_dirs = get_overlaydirs(config, install)

    if is_mounted(overlay_dirs):
        return

    if check_fstab(overlay_dirs):
        return

    cols, _ = shutil.get_terminal_size()
    width = cols - 2
    if logger.isEnabledFor(logging.DEBUG):
        width -= len("info: ")

    def style_manref(ref: str):
        ref = ref.split("`")[1].split()[0]
        return (
            click.style(ref[:-3], fg="green")
            + click.style(ref[-3], fg="red")
            + click.style(ref[-2], fg="blue")
            + click.style(ref[-1], fg="red")
        )

    # extract "seealso" directives from text
    seealso, about = partition(
        lambda line: line.startswith(".. seealso:: "), ABOUT.splitlines(keepends=True)
    )
    about = "".join(about)
    seealso = ", ".join([line[len(".. seealso:: ") :] for line in seealso])

    logger.info(click.style("!!PLEASE READ!!", fg="yellow", bold=True))
    logger.info(
        "\n\n\n".join(
            textwrap.fill(para, width=width) for para in about.split("\n\n\n")
        )
        + "\n\n"
    )
    logger.info(click.style("SEE ALSO", fg="yellow"))
    logger.info(
        ANSITextWrapper(
            width=width,
            initial_indent="\t",
            subsequent_indent="\t",
            break_long_words=False,
            break_on_hyphens=False,
        ).fill(", ".join([style_manref(ref) for ref in seealso.split(",")]))
    )

    if clickExt.confirm_ext("Add an entry to /etc/fstab?", default=True):
        fstab_comment = build_fstab_comment()
        fstab_entry = build_fstab_entry(overlay_dirs)

        if os.geteuid() == 0:
            with open("/etc/fstab", "a") as fstab:
                fstab.write(fstab_comment)
                fstab.write(fstab_entry)

        elif not shutil.which("sudo") or (
            subprocess.run(
                [
                    r"printf '%s\n' '{}' '{}' | sudo tee -a /etc/fstab".format(
                        fstab_comment, fstab_entry
                    )
                ],
                shell=True,
            ).returncode
            != 0
        ):
            logger.error(
                "\n".join(
                    [
                        "Unable to append entry. Manually append the following to /etc/fstab:",
                        "",
                        fstab_comment,
                        fstab_entry,
                    ]
                )
            )

    lowerdir = overlay_dirs.lowerdir
    if os.access(lowerdir, os.W_OK):
        logger.warning(
            "It is also recommended to make the base install \
read-only when using an overlay install."
        )
        if clickExt.confirm_ext(f"Make {lowerdir} read-only?", default=True):
            os.chmod(
                lowerdir,
                os.stat(lowerdir).st_mode
                & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH),
            )


def activate(ctx, install: Install):
    overlay_dirs = get_overlaydirs(ctx, install)
    _, upperdir, workdir, mergeddir = overlay_dirs

    if is_mounted(overlay_dirs):
        return

    os.makedirs(upperdir, exist_ok=True)
    os.makedirs(workdir, exist_ok=True)

    # If in a namespace, assume this message already got logged outside of it
    if not in_namespace():
        logger.debug(f"Overlay for '{install.name}' not mounted.")

    mount_cmd = [
        "mount",
        "-t",
        "overlay",
        "overlay",
        mergeddir,
        "-o",
        build_mount_options(*overlay_dirs[:3], fstab=False),
    ]
    if os.geteuid() != 0:
        logger.debug("Attempting to mount without sudo...")
        if subprocess.run(mount_cmd, capture_output=True).returncode == 0:
            logger.debug("Overlay successfully mounted without sudo.")
            return

        if not in_namespace():
            logger.debug("Attempting to mount using unprivileged user namespace...")
            # First check that creating the ns works, we don't have a way to
            # know if a faliure is from 'unshare' or the command it ran
            if (
                subprocess.run(
                    ["unshare", "--mount", "--user", "--map-root-user", "echo"],
                    capture_output=True,
                ).returncode
                == 0
            ):
                logger.debug(
                    "Unprivileged user namespaces available, running program in new namespace..."
                )

                # Make sure any files opened within a ctx (such as UserInfo.cache) are saved
                # *before* running the nested process. Otherwise any changes made by the
                # nested process are lost.
                while ctx:
                    ctx.close()
                    ctx = ctx.parent

                # Run the current command again within a new namespace
                ret = subprocess.run(
                    ["unshare", "--mount", "--user", "--map-root-user", *sys.argv]
                ).returncode
                exit(ret)

        if not shutil.which("sudo"):
            raise click.ClickException(
                "\n".join(
                    [
                        "Could not mount overlay. Run the following command with the necessary privileges:",
                        "",
                        " ".join(mount_cmd),
                    ]
                )
            )
        mount_cmd = ["sudo"] + mount_cmd

    logger.debug("Attempting to mount as superuser...")
    if subprocess.run(mount_cmd).returncode != 0:
        raise click.ClickException(
            "\n".join(
                [
                    "Could not mount overlay. Run the following command with the necessary privileges:",
                    "",
                    " ".join(mount_cmd),
                ]
            )
        )

    logger.debug("Overlay successfully mounted as superuser.")
    if in_namespace():
        logger.info(
            f"Overlay for '{install.name}' successfully mounted using unprivileged user namespace."
        )


def reset(ctx, install: Install):
    data_dir = os.path.join(DATA_DIR, "overlayfs", install.name)
    subprocess.run(["umount", install.path])
    shutil.rmtree(data_dir)
    os.mkdir(data_dir)
    activate(ctx, install)
