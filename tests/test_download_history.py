"""Tests for the download-history database used by the Creator tab."""

import os

from kemonodownloader.download_history import (
    DownloadHistoryDB,
    iso_to_local_date,
    utc_now_iso,
)

EARLY = "2026-01-02T03:04:05+00:00"
LATER = "2026-06-07T08:09:10+00:00"


def test_record_and_read_back(tmp_path):
    db = DownloadHistoryDB(str(tmp_path))
    assert db.count() == 0
    assert db.get_post_times("patreon", "123") == {}
    assert db.get_creator_time("patreon", "123") is None

    db.record_post("patreon", "123", "p1", EARLY)

    assert db.count() == 1
    assert db.get_post_times("patreon", "123") == {"p1": EARLY}
    assert db.get_creator_time("patreon", "123") == EARLY


def test_database_file_is_named_and_persists(tmp_path):
    db = DownloadHistoryDB(str(tmp_path))
    db.record_post("patreon", "123", "p1", EARLY)

    assert os.path.exists(os.path.join(str(tmp_path), "download_history.db"))

    reopened = DownloadHistoryDB(str(tmp_path))
    assert reopened.get_post_times("patreon", "123") == {"p1": EARLY}


def test_default_timestamp_is_now(tmp_path):
    db = DownloadHistoryDB(str(tmp_path))
    db.record_post("patreon", "123", "p1")

    stored = db.get_creator_time("patreon", "123")
    assert stored
    # Round-trips as a real timestamp, and is not in the past.
    assert iso_to_local_date(stored)
    assert stored[:4] in utc_now_iso()[:4]


def test_recording_the_same_post_overwrites(tmp_path):
    db = DownloadHistoryDB(str(tmp_path))
    db.record_post("patreon", "123", "p1", EARLY)
    db.record_post("patreon", "123", "p1", LATER)

    assert db.count() == 1
    assert db.get_post_times("patreon", "123") == {"p1": LATER}


def test_creators_and_services_are_isolated(tmp_path):
    db = DownloadHistoryDB(str(tmp_path))
    db.record_post("patreon", "123", "p1", EARLY)
    db.record_post("patreon", "456", "p1", LATER)
    db.record_post("fanbox", "123", "p1", LATER)

    # Same post id under a different creator / service is a separate record.
    assert db.count() == 3
    assert db.get_post_times("patreon", "123") == {"p1": EARLY}
    assert db.get_post_times("patreon", "456") == {"p1": LATER}
    assert db.get_post_times("fanbox", "123") == {"p1": LATER}


def test_creator_time_is_the_newest_post(tmp_path):
    db = DownloadHistoryDB(str(tmp_path))
    db.record_post("patreon", "123", "p1", LATER)
    db.record_post("patreon", "123", "p2", EARLY)

    assert db.get_creator_time("patreon", "123") == LATER


def test_missing_identity_is_ignored(tmp_path):
    db = DownloadHistoryDB(str(tmp_path))
    db.record_post("", "123", "p1", EARLY)
    db.record_post("patreon", "", "p1", EARLY)
    db.record_post("patreon", "123", "", EARLY)

    assert db.count() == 0


def test_ids_are_coerced_to_text(tmp_path):
    db = DownloadHistoryDB(str(tmp_path))
    db.record_post("patreon", 123, 456, EARLY)

    assert db.get_post_times("patreon", "123") == {"456": EARLY}


def test_forget_post_and_clear(tmp_path):
    db = DownloadHistoryDB(str(tmp_path))
    db.record_post("patreon", "123", "p1", EARLY)
    db.record_post("patreon", "123", "p2", LATER)

    db.forget_post("patreon", "123", "p1")
    assert db.get_post_times("patreon", "123") == {"p2": LATER}
    assert db.get_creator_time("patreon", "123") == LATER

    db.clear()
    assert db.count() == 0
    assert db.get_creator_time("patreon", "123") is None


def test_iso_to_local_date_handles_bad_values():
    assert iso_to_local_date(None) == ""
    assert iso_to_local_date("") == ""
    assert iso_to_local_date("not-a-date") == ""

    # Naive timestamps are treated as UTC rather than rejected.
    assert iso_to_local_date("2026-01-02T03:04:05") == iso_to_local_date(EARLY)


def test_utc_now_iso_round_trips_through_the_display_helper():
    stamp = utc_now_iso()

    assert stamp.endswith("+00:00")
    assert iso_to_local_date(stamp)
