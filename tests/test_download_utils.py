"""Tests for the shared download plumbing in :mod:`download_utils`."""

import time
from types import SimpleNamespace

import pytest

from kemonodownloader import download_utils as du


class TestProgressTracker:
    def test_reports_each_percentage_once(self):
        tracker = du.ProgressTracker(1000)
        reported = [tracker.advance(10) for _ in range(100)]

        assert [value for value in reported if value is not None] == list(range(1, 101))

    def test_one_chunk_per_percent_is_at_most_a_hundred_and_one(self):
        total = 100 * 1024 * 1024
        tracker = du.ProgressTracker(total)
        reported = 0
        sent = 0
        while sent < total:
            step = min(du.DOWNLOAD_CHUNK_SIZE, total - sent)
            if tracker.advance(step) is not None:
                reported += 1
            sent += step

        assert reported <= 101

    def test_unknown_size_reports_zero_once(self):
        tracker = du.ProgressTracker(0)

        assert tracker.advance(4096) == 0
        assert tracker.advance(4096) is None

    def test_never_exceeds_one_hundred(self):
        tracker = du.ProgressTracker(10)

        assert tracker.advance(1000) == 100
        assert tracker.advance(1) is None

    def test_negative_total_is_treated_as_unknown(self):
        assert du.ProgressTracker(-5).advance(1) == 0


class TestResponseContentLength:
    @staticmethod
    def _response(headers):
        return SimpleNamespace(headers=headers)

    def test_plain_length(self):
        assert (
            du.response_content_length(self._response({"content-length": "42"})) == 42
        )

    def test_encoded_body_has_an_unknown_decoded_size(self):
        response = self._response({"content-length": "42", "content-encoding": "gzip"})

        assert du.response_content_length(response) == 0

    def test_identity_encoding_is_a_plain_length(self):
        response = self._response(
            {"content-length": "42", "content-encoding": "identity"}
        )

        assert du.response_content_length(response) == 42

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"content-length": "soon"},
            {"content-length": None},
            {"content-length": "-1"},
        ],
    )
    def test_missing_or_garbage_is_unknown(self, headers):
        assert du.response_content_length(self._response(headers)) == 0

    def test_object_without_headers_is_unknown(self):
        assert du.response_content_length(object()) == 0


class TestConnectionGuard:
    def test_no_lock_outside_windows_python_314(self, monkeypatch):
        monkeypatch.setattr(
            du, "sys", SimpleNamespace(platform="linux", version_info=(3, 14, 0))
        )

        assert not hasattr(du.create_connection_guard(), "acquire")

    def test_no_lock_on_older_windows(self, monkeypatch):
        monkeypatch.setattr(
            du, "sys", SimpleNamespace(platform="win32", version_info=(3, 13, 4))
        )

        assert not hasattr(du.create_connection_guard(), "acquire")

    def test_lock_on_windows_python_314(self, monkeypatch):
        monkeypatch.setattr(
            du, "sys", SimpleNamespace(platform="win32", version_info=(3, 14, 0))
        )
        guard = du.create_connection_guard()

        assert hasattr(guard, "acquire")
        with guard:
            pass


class TestIsPawchiveHost:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://pawchive.pw/data/1.png", True),
            ("https://file.pawchive.pw/data/1.png", True),
            ("https://img.pawchive.xyz/thumbnail/data/1.png", True),
            ("https://pawchive.pw:8443/data/1.png", True),
            ("https://kemono.cr/data/1.png", False),
            ("https://notpawchive.pw/data/1.png", False),
            ("pawchive.pw", False),
            ("", False),
        ],
    )
    def test_matches_any_pawchive_suffix(self, url, expected):
        assert du.is_pawchive_host(url) is expected


class TestRequestGate:
    def test_spaces_successive_grants(self):
        gate = du.RequestGate(0.05)
        started = time.monotonic()

        assert gate.acquire() is True
        assert gate.acquire() is True

        assert time.monotonic() - started >= 0.04

    def test_zero_interval_never_waits(self):
        gate = du.RequestGate(0)

        assert gate.acquire() is True
        assert gate.acquire() is True

    def test_stops_waiting_when_the_run_is_cancelled(self):
        gate = du.RequestGate(5.0)

        assert gate.acquire() is True
        assert gate.acquire(lambda: False) is False

    def test_reset_clears_the_pending_wait(self):
        gate = du.RequestGate(5.0)
        assert gate.acquire() is True

        gate.reset()

        assert gate.acquire() is True

    def test_only_pawchive_urls_consume_a_slot(self):
        du.reset_pawchive_gate()

        assert du.acquire_pawchive_slot("https://kemono.cr/data/a.png") is True
        assert du.acquire_pawchive_slot("https://file.pawchive.pw/data/a.png") is True
        # The Pawchive grant armed the gate, so the next one has to wait.
        assert (
            du.acquire_pawchive_slot(
                "https://file.pawchive.pw/data/b.png", lambda: False
            )
            is False
        )

    def test_defer_pushes_the_next_grant_back(self):
        gate = du.RequestGate(0.01)
        gate.defer(0.05)
        started = time.monotonic()

        assert gate.acquire() is True

        assert time.monotonic() - started >= 0.04

    def test_wait_out_sleeps_for_a_deferral(self):
        gate = du.RequestGate(0)
        gate.defer(0.05)
        started = time.monotonic()

        assert gate.wait_out() is True

        assert time.monotonic() - started >= 0.04

    def test_wait_out_does_not_reserve_a_slot(self):
        gate = du.RequestGate(0.05)

        assert gate.wait_out() is True
        # Nothing was granted, so the first acquire must not wait.
        started = time.monotonic()
        assert gate.acquire() is True
        assert time.monotonic() - started < 0.04

    def test_wait_out_stops_when_the_run_is_cancelled(self):
        gate = du.RequestGate(0)
        gate.defer(5.0)

        assert gate.wait_out(lambda: False) is False


class TestDirectUrlRegistry:
    def test_remembers_and_forgets(self):
        du.remember_direct_url(
            "https://file.pawchive.pw/data/a.png", "https://n1.x/a.png"
        )

        assert (
            du.direct_url_for("https://file.pawchive.pw/data/a.png")
            == "https://n1.x/a.png"
        )

        du.forget_direct_url("https://file.pawchive.pw/data/a.png")
        assert du.direct_url_for("https://file.pawchive.pw/data/a.png") is None

    def test_ignores_empty_values(self):
        du.remember_direct_url("", "https://n1.x/a.png")
        du.remember_direct_url("https://file.pawchive.pw/data/a.png", "")

        assert du.direct_url_for("") is None
        assert du.direct_url_for("https://file.pawchive.pw/data/a.png") is None

    def test_forgetting_an_unknown_url_is_harmless(self):
        du.forget_direct_url("https://never/seen.png")

        assert du.direct_url_for("https://never/seen.png") is None

    def test_clear_drops_everything(self):
        du.remember_direct_url("a", "b")

        du.clear_direct_urls()

        assert du.direct_url_for("a") is None


class TestPreparationRateLimitCounts:
    def test_counts_only_403_and_429(self):
        du.note_rate_limit(403)
        du.note_rate_limit(429)
        du.note_rate_limit(500)
        du.note_rate_limit("nope")

        assert du.rate_limit_counts() == {403: 1, 429: 1}

    def test_reset_clears_them(self):
        du.note_rate_limit(429)

        du.reset_rate_limit_counts()

        assert du.rate_limit_counts() == {}
