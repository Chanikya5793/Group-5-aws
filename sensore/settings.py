"""Compatibility shim.

This project uses sensore_project.settings as the active settings module.
Importing from sensore.settings is supported for legacy scripts.
"""

from sensore_project.settings import *  # noqa: F403,F401
