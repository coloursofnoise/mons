# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
#
#
# -- Path setup --------------------------------------------------------------
#
# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
# import os
# import sys
# sys.path.insert(0, os.path.abspath('..'))
import os
import sys

sys.path.append(os.path.abspath("./_extensions"))

# -- Project information -----------------------------------------------------

project = "mons"
author = "coloursofnoise"
copyright = "2022-2023, coloursofnoise"


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx_click",
    "myst_parser",
    "sphinx.ext.autodoc",
    "autodoc_ext",
    "glossarygen",
    "manpages_ext",
]

suppress_warnings = ["myst.header"]

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# Don't prepend module names to object names.
add_module_names = False

# Don't include values for autodoc members.
autodoc_default_options = {"no-value": True}

autodoc_member_order = "bysource"


def process_options(app, ctx, lines):
    meta_options = getattr(ctx.command, "meta_options", {})
    if not meta_options:
        return

    for section, opts in meta_options.items():
        lines.append(".. rubric:: {}".format(section))
        lines.append("")
        for opt, desc in opts:
            lines.append(".. option:: {}".format(opt))
            lines.append("")
            lines.append("    " + desc)


def setup(app):
    app.connect("sphinx-click-process-options", process_options)


# -- Options for manual page output ------------------------------------------

man_pages = [
    ("everest", "mons", "", "", "1"),
    ("mods", "mons-mods", "", "", "1"),
    ("config", "mons", "", "", "5"),
    ("glossary", "mons-glossary", "", "", "7"),
    ("overlayfs", "mons-overlayfs", "", "", "7"),
]

# Use 'man/man[0-9]' section sub-directories
man_make_section_directory = True

# URL to use when displaying manpage links in HTML pages.
manpages_url = "https://www.man7.org/linux/man-pages/man{section}/{page}.{section}.html"


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "alabaster"

html_theme_options = {
    "github_user": "coloursofnoise",
    "github_repo": "mons",
    "github_type": "star",
    "github_count": "true",
}

html_sidebars = {
    "**": [
        "about.html",
        "project_links.html",
        "navigation.html",
        "relations.html",
        "searchbox.html",
        "donate.html",
    ]
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
# html_static_path = ['_static']
