"""Where the app keeps its own working data, apart from the user's posts.

The Creator tab writes thumbnails and small SQLite databases (file hashes,
download history, saved config profiles) while it works. Those are the app's
business, not part of the collection, so they live next to the application in
``extras``: one folder to back up or move, and nothing scattered through the
Save Directory.

The location is fixed - there is no setting for it any more. Two escape hatches
remain: ``KEMONO_DOWNLOADER_DATA_DIR`` (tests, debugging) and the old per-user
folder when the application folder is not writable (a system-wide install under
Program Files), so a read-only install still works.
"""

import os
import shutil
import sys

# Folder inside the application directory that holds the app's own data.
APP_SUBFOLDER = "extras"

# The pre-``extras`` per-user location. Still the fallback for read-only
# installs, and read once to migrate an existing profile.
LEGACY_FOLDER = "Kemono Downloader"

# Lets the test suite (and anyone debugging) point the program data somewhere
# else without touching the real profile. Not a documented user setting.
DATA_DIR_ENV = "KEMONO_DOWNLOADER_DATA_DIR"

# The two folders the app needs inside the data directory.
CACHE_FOLDER = "Cache"
OTHER_FILES_FOLDER = "Other Files"

# Resolved once per process: the writability probe writes a file, and every
# cache/history lookup asks for the path.
_resolved_directory = None


def app_root_directory():
    """The folder the application lives in.

    A frozen build (Briefcase, PyInstaller) sits next to its executable; a
    source checkout is two levels above this package (``src/kemonodownloader``).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    package_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(package_dir))


def per_user_directory():
    """The platform's per-user folder for the app (still the Save Directory default)."""
    if sys.platform == "win32":
        return os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), LEGACY_FOLDER)
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Application Support/{LEGACY_FOLDER}")
    fallback = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(os.getenv("XDG_DATA_HOME", fallback), LEGACY_FOLDER)


def _is_writable(path):
    """True when *path* can be created and written to."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write-test")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("")
        os.remove(probe)
        return True
    except OSError:
        return False


def default_data_directory():
    """Return the folder holding the app's own data.

    ``<application>/extras``, or the old per-user folder when that cannot be
    written to (Program Files installs run read-only for standard users).
    """
    preferred = os.path.join(app_root_directory(), APP_SUBFOLDER)
    if _is_writable(preferred):
        return preferred
    return per_user_directory()


def migrate_legacy_data(target, legacy_directory=None):
    """Copy an existing per-user profile into *target*, once.

    Moving the data next to the application would otherwise start from empty
    databases: every file would look new (a full re-download) and saved page
    configs would vanish. Copies, never moves, so nothing is lost if the user
    ends up back on the old location.
    """
    legacy = legacy_directory or per_user_directory()
    if os.path.normcase(os.path.abspath(legacy)) == os.path.normcase(
        os.path.abspath(target)
    ):
        return False
    source = os.path.join(legacy, OTHER_FILES_FOLDER)
    if not os.path.isdir(source):
        return False
    destination = os.path.join(target, OTHER_FILES_FOLDER)
    marker = os.path.join(target, ".migrated-from-legacy")
    if os.path.exists(marker) or os.path.exists(
        os.path.join(destination, "file_hashes.db")
    ):
        return False
    try:
        os.makedirs(target, exist_ok=True)
        shutil.copytree(source, destination, dirs_exist_ok=True)
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write(legacy)
        return True
    except OSError:
        return False


def reset_resolution():
    """Forget the cached data directory (tests only)."""
    global _resolved_directory
    _resolved_directory = None


def data_directory(configured=None):
    """Return the folder holding the app's own data.

    *configured* is accepted for older callers and ignored: the location is
    fixed now. The environment override wins so tests never touch the real
    profile.
    """
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return override
    global _resolved_directory
    if _resolved_directory is None:
        resolved = default_data_directory()
        migrate_legacy_data(resolved)
        _resolved_directory = resolved
    return _resolved_directory


def cache_dir(configured=None):
    """Return the thumbnail cache folder."""
    return os.path.join(data_directory(configured), CACHE_FOLDER)


def other_files_dir(configured=None):
    """Return the folder holding the databases and saved config profiles."""
    return os.path.join(data_directory(configured), OTHER_FILES_FOLDER)

