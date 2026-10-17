"""Tests for the capped retry timings shared by the downloaders.

The retry waits used to be an uncapped ``2 ** attempt`` schedule (which
reached ~1.7e13 seconds at attempt 44) plus a flat 5 second countdown on
every post-data retry.  These tests pin the new short, capped behaviour and
make sure all four ``make_robust_request`` copies share it.
"""

from types import SimpleNamespace

import pytest

import kemonodownloader.creator_downloader as cd
import kemonodownloader.post_downloader as pd
from kemonodownloader.retry_policy import (
    API_RETRY_BASE_DELAY,
    API_RETRY_MAX_DELAY,
    COUNTDOWN_MAX_SECONDS,
    RETRY_AFTER_CAP,
    api_retry_delay,
    countdown_seconds,
    is_terminal_status,
    retry_after_seconds,
)

URL = "https://kemono.cr/api/v1/patreon/user/1/post/2"


class ApiStub:
    """Minimal host object for the four make_robust_request copies."""

    def __init__(self, max_retries):
        self.settings = SimpleNamespace(
            api_request_max_retries=max_retries, settings_tab=None
        )
        self.parent = SimpleNamespace(settings_tab=None)
        self.log = SimpleNamespace(emit=lambda *args, **kwargs: None)

    def _create_thread_settings(self):
        return self.settings


CALLERS = {
    "post_detection": pd.PostDetectionThread.make_robust_request,
    "file_prep": pd.FilePreparationThread.make_robust_request,
    "download": pd.DownloadThread.make_robust_request,
    "post_tab": pd.PostDownloaderTab.make_robust_request,
}


def patch_network(monkeypatch, responses):
    """Serve *responses* in order; exceptions are raised, not returned."""
    calls = {"count": 0}

    def fake_get(url, headers=None, timeout=10):
        index = min(calls["count"], len(responses) - 1)
        calls["count"] += 1
        item = responses[index]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(
        pd, "get_session", lambda *args, **kwargs: SimpleNamespace(get=fake_get)
    )
    monkeypatch.setattr(pd, "get_headers", lambda: {"User-Agent": "test"})
    return calls


def record_sleeps(monkeypatch):
    sleeps = []
    monkeypatch.setattr(pd.time, "sleep", lambda seconds: sleeps.append(seconds))
    return sleeps


class TestApiRetryDelay:
    def test_linear_ramp_replaces_the_exponential_one(self):
        assert [api_retry_delay(attempt) for attempt in range(7)] == [
            API_RETRY_BASE_DELAY,
            2.0,
            3.0,
            4.0,
            API_RETRY_MAX_DELAY,
            API_RETRY_MAX_DELAY,
            API_RETRY_MAX_DELAY,
        ]

    def test_large_attempts_stay_capped(self):
        # 2 ** 50 seconds is longer than the age of the universe.
        assert api_retry_delay(50) == API_RETRY_MAX_DELAY

    def test_negative_attempt_is_treated_as_the_first(self):
        assert api_retry_delay(-2) == API_RETRY_BASE_DELAY

    def test_retry_after_header_wins(self):
        response = SimpleNamespace(headers={"Retry-After": "7"})
        assert api_retry_delay(0, response) == 7.0

    def test_retry_after_header_is_capped(self):
        response = SimpleNamespace(headers={"Retry-After": "999"})
        assert api_retry_delay(0, response) == RETRY_AFTER_CAP

    def test_retry_after_garbage_falls_back_to_the_ramp(self):
        response = SimpleNamespace(headers={"Retry-After": "soon"})
        assert api_retry_delay(1, response) == 2.0

    def test_response_without_headers_uses_the_ramp(self):
        response = SimpleNamespace()
        assert retry_after_seconds(response) is None
        assert api_retry_delay(0, response) == API_RETRY_BASE_DELAY


class TestCountdownSeconds:
    def test_grows_by_one_second_and_caps(self):
        assert [countdown_seconds(attempt, 2) for attempt in range(1, 8)] == [
            2,
            3,
            4,
            COUNTDOWN_MAX_SECONDS,
            COUNTDOWN_MAX_SECONDS,
            COUNTDOWN_MAX_SECONDS,
            COUNTDOWN_MAX_SECONDS,
        ]

    def test_zero_base_disables_the_countdown(self):
        assert countdown_seconds(4, 0) == 0

    def test_larger_explicit_base_is_not_shortened(self):
        assert countdown_seconds(1, 10) == 10
        assert countdown_seconds(5, 10) == 10

    def test_flat_five_second_base_is_unchanged(self):
        # Callers that asked for 5s explicitly keep their old behaviour.
        assert [countdown_seconds(attempt, 5) for attempt in range(1, 4)] == [5, 5, 5]


@pytest.mark.parametrize("status_code", [400, 401, 402, 404, 405, 406, 410, 451])
def test_terminal_statuses_are_not_retried(status_code):
    assert is_terminal_status(status_code)


@pytest.mark.parametrize("status_code", [200, 403, 429, 500, 503, None, "nope"])
def test_other_statuses_are_retryable(status_code):
    assert not is_terminal_status(status_code)


@pytest.mark.parametrize("name", sorted(CALLERS))
def test_every_copy_uses_the_capped_schedule(name, monkeypatch):
    sleeps = record_sleeps(monkeypatch)
    patch_network(monkeypatch, [RuntimeError("connection reset")])

    assert CALLERS[name](ApiStub(max_retries=8), URL) is None
    assert sleeps == [1.0, 2.0, 3.0, 4.0, 4.0, 4.0, 4.0]
    assert max(sleeps) <= API_RETRY_MAX_DELAY


@pytest.mark.parametrize("name", sorted(CALLERS))
def test_terminal_status_fails_fast_without_sleeping(name, monkeypatch):
    sleeps = record_sleeps(monkeypatch)
    calls = patch_network(monkeypatch, [SimpleNamespace(status_code=404)])

    assert CALLERS[name](ApiStub(max_retries=5), URL) is None
    assert calls["count"] == 1
    assert sleeps == []


@pytest.mark.parametrize("name", sorted(CALLERS))
def test_403_falls_back_to_alternative_headers_without_sleeping(name, monkeypatch):
    sleeps = record_sleeps(monkeypatch)
    ok = SimpleNamespace(status_code=200)
    calls = patch_network(monkeypatch, [SimpleNamespace(status_code=403), ok])

    assert CALLERS[name](ApiStub(max_retries=2), URL) is ok
    assert calls["count"] == 2
    assert sleeps == []


@pytest.mark.parametrize("name", sorted(CALLERS))
def test_rate_limit_response_now_backs_off_instead_of_spinning(name, monkeypatch):
    sleeps = record_sleeps(monkeypatch)
    ok = SimpleNamespace(status_code=200)
    patch_network(monkeypatch, [SimpleNamespace(status_code=429), ok])

    assert CALLERS[name](ApiStub(max_retries=3), URL) is ok
    assert sleeps == [API_RETRY_BASE_DELAY]


@pytest.mark.parametrize("name", sorted(CALLERS))
def test_server_retry_after_is_honoured_by_the_loop(name, monkeypatch):
    sleeps = record_sleeps(monkeypatch)
    throttled = SimpleNamespace(status_code=429, headers={"Retry-After": "7"})
    patch_network(monkeypatch, [throttled, SimpleNamespace(status_code=200)])

    assert CALLERS[name](ApiStub(max_retries=3), URL) is not None
    assert sleeps == [7.0]


@pytest.mark.parametrize("name", sorted(CALLERS))
def test_zero_retries_makes_no_request(name, monkeypatch):
    sleeps = record_sleeps(monkeypatch)
    calls = patch_network(monkeypatch, [SimpleNamespace(status_code=200)])

    assert CALLERS[name](ApiStub(max_retries=0), URL) is None
    assert calls["count"] == 0
    assert sleeps == []


def test_post_detection_logs_the_final_transport_error(monkeypatch):
    record_sleeps(monkeypatch)
    patch_network(monkeypatch, [RuntimeError("boom")])
    messages = []
    stub = ApiStub(max_retries=1)
    stub.log = SimpleNamespace(emit=lambda message, level: messages.append(message))

    assert pd.PostDetectionThread.make_robust_request(stub, URL) is None
    assert any("Request failed after 1 attempts" in message for message in messages)


class FetchStub:
    """State needed by FilePreparationThread.fetch_post_data."""

    def __init__(self, post_data_max_retries=2):
        self.settings = SimpleNamespace(
            post_data_max_retries=post_data_max_retries, settings_tab=None
        )
        self.url = "https://kemono.cr/patreon/user/1/post/2"
        self.domain_config = {"api_base": "https://kemono.cr/api/v1"}
        self.is_running = True
        self.log = SimpleNamespace(emit=lambda *args, **kwargs: None)
        self.inner_retries = []

    def make_robust_request(self, url, max_retries=None):
        self.inner_retries.append(max_retries)
        return None


def test_fetch_post_data_stops_stacking_inner_retries(monkeypatch):
    sleeps = record_sleeps(monkeypatch)
    stub = FetchStub(post_data_max_retries=2)

    assert pd.FilePreparationThread.fetch_post_data(stub, "2") is None
    # The inner helper owns retrying now: one request per outer attempt.
    assert stub.inner_retries == [1, 1]
    # One countdown of 2 seconds (two 1s ticks) instead of the old flat 5.
    assert sleeps == [1, 1]


def test_creator_fetch_and_detect_uses_the_short_countdown(monkeypatch):
    sleeps = []
    monkeypatch.setattr(cd.time, "sleep", lambda seconds: sleeps.append(seconds))
    responses = [
        SimpleNamespace(status_code=429),
        SimpleNamespace(status_code=200, json=lambda: {"post": {}}),
    ]
    monkeypatch.setattr(
        cd,
        "get_session",
        lambda *args, **kwargs: SimpleNamespace(get=lambda *a, **k: responses.pop(0)),
    )
    monkeypatch.setattr(cd, "get_headers", lambda: {"User-Agent": "test"})
    monkeypatch.setattr(
        cd,
        "get_domain_config",
        lambda url: {
            "api_base": "https://kemono.cr/api/v1",
            "referer": "https://kemono.cr/",
        },
    )

    class Stub:
        settings = SimpleNamespace(post_data_max_retries=3, settings_tab=None)
        creator_ext_checks = {}
        log = SimpleNamespace(emit=lambda *args, **kwargs: None)

        def detect_files(self, post, allowed_extensions, domain_config):
            return []

    result = cd.FilePreparationThread.fetch_and_detect_files(
        Stub(), "2", "https://kemono.cr/patreon/user/1"
    )

    assert result == ("2", [])
    # 2 second countdown (two ticks) rather than the old five.
    assert sleeps == [1, 1]
