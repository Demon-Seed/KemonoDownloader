"""Where the app keeps its own working data, apart from the user's posts.

The Creator tab writes thumbnails and two small SQLite databases while it
works. Those are the app's business, not part of the collection, so they live
in a fixed per-user folder: pointing the Save Directory at a library must not
scatter ``Cache`` and ``Other Files`` through it, and deleting or repointing
that library must not throw away the duplicate/naming memory.

The data folder itself is a setting (``data_directory``). This module only
resolves it: an explicit value wins, then the environment override, then the
platform default - which is deliberately the same default the Save Directory
uses, so a fresh install keeps both in one place until the user splits them.
"""

import os
import sys

# Folder name for the app's own data. Shared with the Save Directory default so
# the two cannot drift apart.
APP_DATA_FOLDER = "Kemono Downloader"

# Lets the test suite (and anyone debugging) point the program data somewhere
# else without touching the real profile. Not a documented user setting.
DATA_DIR_ENV = "KEMONO_DOWNLOADER_DATA_DIR"

# The two folders the app needs inside the data directory.
CACHE_FOLDER = "Cache"
OTHER_FILES_FOLDER = "Other Files"


def default_data_directory():
    """Return the platform default for the app's own data.

    This is also the default Save Directory, which is why a fresh install has
    them in one place. They are separate settings, so either can move.
    """
    if sys.platform == "win32":
        return os.path.join(
            os.getenv("APPDATA", os.path.expanduser("~")), APP_DATA_FOLDER
        )
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Application Support/{APP_DATA_FOLDER}")
    fallback = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(os.getenv("XDG_DATA_HOME", fallback), APP_DATA_FOLDER)


def data_directory(configured=None):
    """Return the folder holding the app's own data.

    *configured* is the ``data_directory`` setting. The environment override
    takes precedence so tests never write to the real profile.
    """
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return override
    if configured:
        return str(configured)
    return default_data_directory()


def cache_dir(configured=None):
    """Return the thumbnail cache folder."""
    return os.path.join(data_directory(configured), CACHE_FOLDER)


def other_files_dir(configured=None):
    """Return the folder holding the hash and download-history databases."""
    return os.path.join(data_directory(configured), OTHER_FILES_FOLDER)
