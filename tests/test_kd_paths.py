"""Where the app keeps its own working data.

Cache/ and Other Files/ hold thumbnails and the SQLite databases. They live in
``extras`` next to the application - never inside the Save Directory, so a
library folder only ever holds saved posts - and there is no setting for them.
"""

import os
import sys

import pytest

from kemonodownloader import kd_paths


@pytest.fixture(autouse=True)
def _fresh_resolution(monkeypatch, tmp_path):
    """Every test resolves from scratch, inside the sandbox.

    The application root is redirected too: otherwise the writability probe
    would create the real ``extras`` folder in the checkout.
    """
    monkeypatch.delenv(kd_paths.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(
        kd_paths, "app_root_directory", lambda: str(tmp_path / "app")
    )
    kd_paths.reset_resolution()
    yield
    kd_paths.reset_resolution()


def test_the_data_folder_sits_next_to_the_application():
    expected = os.path.join(kd_paths.app_root_directory(), "extras")

    assert kd_paths.default_data_directory() == expected
    assert os.path.basename(kd_paths.default_data_directory()) == "extras"


def test_a_read_only_install_falls_back_to_the_per_user_folder(monkeypatch):
    """Program Files is not writable for standard users; the app still runs."""
    monkeypatch.setattr(kd_paths, "_is_writable", lambda path: False)

    assert kd_paths.default_data_directory() == kd_paths.per_user_directory()


def test_per_user_directory_platforms(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    assert kd_paths.per_user_directory() == os.path.join(
        str(tmp_path / "AppData"), "Kemono Downloader"
    )

    monkeypatch.setattr(sys, "platform", "darwin")
    assert kd_paths.per_user_directory().replace("\\", "/").endswith(
        "Library/Application Support/Kemono Downloader"
    )

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert kd_paths.per_user_directory() == os.path.join(
        str(tmp_path / "xdg"), "Kemono Downloader"
    )


def test_a_configured_path_is_ignored(monkeypatch, tmp_path):
    """The old setting cannot move the data any more."""
    monkeypatch.setattr(kd_paths, "_is_writable", lambda path: True)

    assert kd_paths.data_directory(str(tmp_path / "elsewhere")) == (
        kd_paths.default_data_directory()
    )


def test_the_environment_override_still_wins(monkeypatch, tmp_path):
    """Tests rely on this to stay out of the real profile."""
    monkeypatch.setenv(kd_paths.DATA_DIR_ENV, str(tmp_path / "isolated"))

    assert kd_paths.data_directory(str(tmp_path / "elsewhere")) == str(
        tmp_path / "isolated"
    )


def test_cache_and_other_files_sit_inside_the_data_directory():
    resolved = kd_paths.data_directory()

    assert kd_paths.cache_dir() == os.path.join(resolved, "Cache")
    assert kd_paths.other_files_dir() == os.path.join(resolved, "Other Files")


def test_migrate_copies_the_old_profile_once(monkeypatch, tmp_path):
    """Moving the folder must not mean losing the databases."""
    legacy = tmp_path / "legacy"
    (legacy / "Other Files").mkdir(parents=True)
    (legacy / "Other Files" / "file_hashes.db").write_bytes(b"hash-db")
    target = tmp_path / "extras"
    target.mkdir()

    assert kd_paths.migrate_legacy_data(str(target), legacy_directory=str(legacy)) is True
    copied = target / "Other Files" / "file_hashes.db"
    assert copied.read_bytes() == b"hash-db"
    # The original stays where it was: this copies, it never moves.
    assert (legacy / "Other Files" / "file_hashes.db").exists()

    # Second run is a no-op.
    assert kd_paths.migrate_legacy_data(str(target), legacy_directory=str(legacy)) is False


def test_migrate_leaves_an_existing_target_alone(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy"
    (legacy / "Other Files").mkdir(parents=True)
    (legacy / "Other Files" / "file_hashes.db").write_bytes(b"old")
    target = tmp_path / "extras"
    (target / "Other Files").mkdir(parents=True)
    (target / "Other Files" / "file_hashes.db").write_bytes(b"new")

    assert kd_paths.migrate_legacy_data(str(target), legacy_directory=str(legacy)) is False
    assert (target / "Other Files" / "file_hashes.db").read_bytes() == b"new"
