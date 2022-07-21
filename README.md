# MONS - CommandLine Celeste Mod Manager

[![PyPI](https://img.shields.io/pypi/v/mons.svg)](https://pypi.python.org/pypi/mons)
[![Documentation Status](https://readthedocs.org/projects/mons/badge/?version=latest)](https://mons.coloursofnoise.ca/en/latest/?badge=latest)
[![GameBanana](https://img.shields.io/static/v1?label=GameBanana&message=9963&color=yellow)](https://gamebanana.com/tools/9963)

<!-- sphinx start -->
`mons` is a commandline [Everest](https://everestapi.github.io/) installer and mod manager for [Celeste](http://www.celestegame.com/).

It was originally built for productivity when working on Everest, but can be used by players and developers alike.

**This program requires basic competency using the [commandline](https://en.wikipedia.org/wiki/Command-line_interface) for your operating system.** For a graphical installer, please use [Olympus](https://everestapi.github.io/#installing-everest) instead.

## Install:
### Using [pipx](https://pypa.github.io/pipx/) (recommended):
```console
$ pipx install mons
```

### Using pip:
```console
$ python3 -m pip install --user mons
```

## Usage:

At any time, add the `--help` flag to print usage information for the current command.

A copy of this documentation is hosted online at [mons.coloursofnoise.ca](https://mons.coloursofnoise.ca).

```console
$ mons --help
$ mons install --help
```

### Setup
The first step is to add a reference for your Celeste install. **For the purposes of this documentation, it will be assumed that the install is named `main`.**

```console
$ mons add main path/to/Celeste/install
```

Every command that operates on a Celeste install (pretty much everything except `list` and `config`) will require the install name as the first argument.

### Everest
Installing Everest can be done with a variety of options, including branch name (`stable`/`beta`/`dev`), build number (`3366`), or zip artifact (`--zip /path/to/zip/archive`).

Using the `--latest` flag will always install the most recent build available.

```console
$ mons install main stable
$ mons install main --latest
```

### Everest from source
`mons` was created with Everest development in mind, and tries to make the process as streamlined as possible. Passing the `--src` option with the path to a copy of the Everest repo to `mons install` will, by default:

1. Run `dotnet build` or `msbuild` in the project folder.
2. Copy updated build artifacts from the build output into the Celeste install folder.
3. Run `miniinstaller.exe` to install Everest from the build artifacts.

On GNU/Linux and macOS, `mons` will use the [MonoKickstart](https://github.com/flibitijibibo/MonoKickstart) executable bundled with Celeste to run `miniinstaller`, so a system install of [mono](https://www.mono-project.com/) is not required.

```console
$ mons install main --src=/path/to/Everest/repo --launch
```

### Mods
`mons` supports Celeste mods that have been posted on [GameBanana](https://gamebanana.com/games/6460), but can also attempt to install from local or remote zip files, including Google Drive share links.

Dependencies will be automatically resolved where possible, and missing dependencies can be resolved at any point using `mons mods resolve`.

The `--search` option when adding mods uses the [GameBanana Search API](https://github.com/max4805/RandomStuffWebsite/blob/main/README.md#gamebanana-search-api) to provide a list of possible matches to install.

```console
$ mons mods add SpringCollab2022
$ mons mods add https://gamebanana.com/mods/53697 # Communal Helper
$ mons mods add --search Helper
$ mons mods update --all
```

<!-- sphinx end -->
-----

**[Everest Website](https://everestapi.github.io/)**

For general feedback and questions ping `@coloursofnoise` on the Celeste Community Discord:

<a href="https://discord.gg/celeste"><img alt="Mt. Celeste Climbing Association" src="https://discordapp.com/api/guilds/403698615446536203/embed.png?style=banner2" /></a>
