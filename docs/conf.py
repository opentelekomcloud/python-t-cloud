"""Sphinx configuration for the SDK documentation."""

import os
import sys

# Add src/ to path so autodoc can find the package
sys.path.insert(0, os.path.abspath("../src"))

# -- Project information -----------------------------------------------------

project = "SDK"
copyright = "2026, Open Telekom Cloud"
author = "Open Telekom Cloud"
release = "0.1.0"

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",        # Google-style docstrings
    "sphinx_autodoc_typehints",   # type hints in docs
    "sphinx.ext.viewcode",        # [source] links
    "sphinx.ext.intersphinx",     # link to Python stdlib docs
]

# Napoleon settings (Google-style)
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_use_param = True
napoleon_use_rtype = True

# Autodoc settings
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_class_signature = "separated"
autodoc_pydantic_model_show_field_summary = False

# Intersphinx — link to Python docs
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}

# -- Options for HTML output -------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 3,
}
