# `everest:` URI Scheme Registration
![Everest 1-Click Install button on GameBanana](https://media.discordapp.net/attachments/850184494220312646/1029860061406838834/unknown.png)
## Linux
```console
$ cp mons.desktop ~/.local/share/applications/mons.desktop
$ xdg-mime default ~/.local/share/applications/mons.desktop "x-scheme-handler/everest"
$ update-desktop-database ~/.local/share/applications
```

# Manual Pages
## Build
> [!NOTE]
> Pre-built man pages are distributed with the `mons` package within `mons/man/`.

```console
$ # run commands in project root
$ pip install -r requirements-dev.txt
$ sphinx-build -b man docs mons/man -d docs/_build
```

## Install
### Linux
```console
$ # run commands in project root
$ mkdir -p /usr/share/man
$ cp -r mons/man /usr/share/man
```
