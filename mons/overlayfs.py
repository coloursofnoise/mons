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
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime

import click
from click import echo

from mons import clickExt
from mons import fs
from mons.config import CACHE_DIR
from mons.config import DATA_DIR
from mons.install import Install


def build_mount_options(lowerdir, upperdir, workdir, fstab=True):
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


def build_fstab_entry(lowerdir, upperdir, workdir, mergeddir):
    return " ".join(
        [
            "overlay",
            mergeddir,
            "overlay",
            build_mount_options(lowerdir, upperdir, workdir),
            "0",
            "0",
        ]
    )


def build_fstab_comment():
    return "# Added by mons " + datetime.now().date().isoformat()


def check_fstab(lowerdir, upperdir, workdir, mergeddir, fstab="/etc/fstab"):
    with open(fstab) as file:
        for line in file.readlines():
            if line.startswith("#") or not line.strip():
                continue
            [fs_spec, fs_file, fs_vfstype, fs_mntops, _, _] = line.split()
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


def is_mounted(lowerdir, upperdir, workdir, mergeddir):
    if os.path.ismount(mergeddir):
        mount_file = "/proc/mounts"
        if not fs.isfile(mount_file):
            # Usually contain the same information (and are often symlinked)
            # but /proc/mounts is more likely to be up to date.
            mount_file = "/etc/mtab"
            assert fs.isfile(mount_file)
        return check_fstab(lowerdir, upperdir, workdir, mergeddir, fstab=mount_file)
    return False


def in_namespace():
    with open("/proc/self/uid_map") as file:
        uid_map = file.read()
        # This will always be the value given for the "default" (nonexistant) namespace
        return uid_map.strip("\n") != "         0          0 4294967295"


def setup(install: Install):
    assert install.overlay_base

    lowerdir = install.overlay_base
    upperdir = os.path.join(DATA_DIR, "overlayfs", install.name)
    workdir = os.path.join(CACHE_DIR, "overlayfs", install.name)
    mergeddir = install.path

    if is_mounted(lowerdir, upperdir, workdir, mergeddir):
        return

    if check_fstab(lowerdir, upperdir, workdir, mergeddir):
        return

    echo(
        """
!!PLEASE READ!!
An Overlay Filesystem allows the contents of one directory to be overlaid on top of another.
This means that Everest can be installed without modifying the base Celeste install, and
without needing a second copy of Celeste.

Mounting a filesystem on linux usually requires superuser permissions, which would require
entering the root password after every reboot. This is rather cumbersome, so a good
alternative is to add an entry to the '/etc/fstab' file for the mount point. With the
'x-systemd.automount' option provided by systemd, the filesystem will only be mounted when
it is accessed.

SEE ALSO mount(8), systemd-automount(5)

If 'mons' is unable to mount the overlay, it will attempt to use an Unprivileged User Namespace.
This can be used to create a container that has superuser privileges that are still isolated from
the rest of the system.

SEE ALSO user_namespaces(7)
"""
    )

    if clickExt.confirm_ext("Add an entry to /etc/fstab?", default=True):
        fstab_comment = build_fstab_comment()
        fstab_entry = build_fstab_entry(lowerdir, upperdir, workdir, mergeddir)

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
            echo(
                "\n".join(
                    [
                        "Unable to append entry. Manually append the following to /etc/fstab:",
                        "",
                        fstab_comment,
                        fstab_entry,
                    ]
                )
            )

    if os.access(lowerdir, os.W_OK):
        echo(
            f"""
It is also recommended to make the base install ('{lowerdir}')
read-only when using an overlay install.
        """
        )
        if clickExt.confirm_ext(f"Make {lowerdir} read-only?", default=True):
            os.chmod(
                lowerdir,
                os.stat(lowerdir).st_mode
                & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH),
            )


def activate(ctx, install: Install):
    assert install.overlay_base

    lowerdir = install.overlay_base
    upperdir = os.path.join(DATA_DIR, "overlayfs", install.name)
    workdir = os.path.join(CACHE_DIR, "overlayfs", install.name)
    mergeddir = install.path

    if is_mounted(lowerdir, upperdir, workdir, mergeddir):
        return

    os.makedirs(upperdir, exist_ok=True)
    os.makedirs(workdir, exist_ok=True)

    if in_namespace():
        echo("Overlay successfully mounted using unprivileged user namespace.")
    else:
        echo(f"Overlay for {install.name} not mounted.")

    mount_cmd = [
        "mount",
        "-t",
        "overlay",
        "overlay",
        mergeddir,
        "-o",
        build_mount_options(lowerdir, upperdir, workdir, fstab=False),
    ]
    if os.geteuid() != 0:
        echo("Attempting to mount without sudo...")
        if subprocess.run(mount_cmd, capture_output=True).returncode == 0:
            echo("Overlay successfully mounted without sudo.")
            return

        if not in_namespace():
            echo("Attempting to mount using unprivileged user namespace...")
            # First check that creating the ns works, we don't have a way to
            # know if a faliure is from 'unshare' or the command it ran
            if (
                subprocess.run(
                    ["unshare", "--mount", "--user", "--map-root-user", "echo"],
                    capture_output=True,
                ).returncode
                == 0
            ):
                echo(
                    "Unprivileged user namespaces available, running program in new namespace.."
                )

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

    echo("Attempting to mount as superuser...")
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
    echo("Overlay successfully mounted as superuser.")


def reset(ctx, install: Install):
    data_dir = os.path.join(DATA_DIR, "overlayfs", install.name)
    subprocess.run(["umount", install.path])
    shutil.rmtree(data_dir)
    os.mkdir(data_dir)
    activate(ctx, install)
