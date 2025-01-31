import sys  # noqa: D100, INP001
from pathlib import Path

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "process-pilot"
copyright = "2024, James Armes"  # noqa: A001
author = "James Armes"
release = "0.4.0"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

sys.path.insert(0, str(Path("..").resolve()))
html_extra_path = ["../LICENSE"]

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "myst_parser",
    "sphinxcontrib.mermaid",
]
myst_fence_as_directive = ["mermaid"]

# Myst Parser settings
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
]

# Mermaid settings
mermaid_init_js = "mermaid.initialize({startOnLoad:true});"

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
