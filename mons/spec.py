VERSIONSPEC = "<VERSIONSPEC>"
"""Describes an Everest build artifact.

VERSIONSPEC can be any of the following:

* An Everest branch name (e.g. 'stable').
* An Everest version number in semver format.
* An Everest build number (the minor version of the build).
* A git ref associated with a CI build (e.g. 'refs/heads/dev,' 'refs/pull/474').
* An artifact download URL.

git refs will *always* look for a CI build, including branch refs.
"""

MODSPEC = "<MODSPEC>"
"""A reference to a mod, used when adding mods to an install.

MODSPEC can be any of the following:

* The 'everest.yaml' name of a mod registered in the Celeste Mod database.
* The GameBanana download URL for a mod.
* The GameBanana submission ID for a mod.
* The GameBanana submission URL for a mod.
* The path to a local zip file.
* A Google Drive share link for a zip file.
* Any URL (fallback).
* An Everest 1-Click Install link for any of the preceeding items.

If a mod is not registered in the Celeste Mod database, and its metadata cannot be determined,
mons will attempt to download and resolve it before installing.
"""
