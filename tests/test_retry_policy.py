"""Tests for the capped retry timings shared by the downloaders.

The retry waits used to be an uncapped ``2 ** attempt`` schedule (which
reached ~1.7e13 seconds at attempt 44) plus a flat 5 second countdown on
every post-data retry.  These tests pin the short, capped behaviour.
"""

from types import SimpleNamespace

import pytest

import kemonodownloader.creator_downloader as cd
from kemonodownloader.retry_policy import (
    API_RETRY_BASE_DELAY,
    API_RETRY_MAX_DELAY,
    COUNTDOWN_MAX_SECONDS,
    RETRY_AFTER_CAP,
    api_retry_delay,
    countdown_seconds,
    is_terminal_error,
    is_terminal_status,
    retry_after_seconds,
)


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


class TestTerminalErrors:
    """``is_terminal_error`` is what the download loop actually asks."""

    @staticmethod
    def _http_error(status_code):
        response = SimpleNamespace(status_code=status_code)

        class _Error(Exception):
            pass

        error = _Error("boom")
        error.response = response
        return error

    @pytest.mark.parametrize("status_code", [400, 404, 410, 451])
    def test_terminal_http_errors_are_final(self, status_code):
        assert is_terminal_error(self._http_error(status_code))

    @pytest.mark.parametrize("status_code", [403, 429, 500, 503])
    def test_waf_and_server_errors_stay_retryable(self, status_code):
        assert not is_terminal_error(self._http_error(status_code))

    def test_errors_without_a_response_stay_retryable(self):
        # Timeouts, connection resets and the size-mismatch sentinel carry no
        # response, so they must never be treated as terminal.
        assert not is_terminal_error(TimeoutError("read timed out"))
        assert not is_terminal_error(SimpleNamespace(response=None))
        assert not is_terminal_error(RuntimeError("size mismatch"))


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
        # The extension snapshot __init__ normally takes on the GUI thread.
        allowed_extensions = []
        log = SimpleNamespace(emit=lambda *args, **kwargs: None)
        is_running = True

        def detect_files(self, post, allowed_extensions, domain_config):
            return []

        def _interruptible_sleep(self, seconds):
            # One recorded wait per countdown tick, like the old flat sleep.
            cd.time.sleep(seconds)

    result = cd.FilePreparationThread.fetch_and_detect_files(
        Stub(), "2", "https://kemono.cr/patreon/user/1"
    )

    assert result == ("2", [])
    # 2 second countdown (two ticks) rather than the old five.
    assert sleeps == [1, 1]


def test_A4_the_countdown_wakes_up_when_the_run_is_stopped(monkeypatch):
    """Cancel must not wait out the retry countdowns."""
    slept = []
    monkeypatch.setattr(cd.time, "sleep", lambda seconds: slept.append(seconds))
    thread = cd.FilePreparationThread.__new__(cd.FilePreparationThread)

    thread.is_running = False
    thread._interruptible_sleep(5)
    assert slept == []

    thread.is_running = True
    thread._interruptible_sleep(0.5)
    assert round(sum(slept), 3) == 0.5
    assert max(slept) <= 0.2  # sliced, so a stop is noticed quickly


def test_A4_the_worker_wait_scales_with_the_retry_budget(monkeypatch):
    thread = cd.FilePreparationThread.__new__(cd.FilePreparationThread)

    thread.settings = SimpleNamespace(post_data_max_retries=7)
    assert thread._worker_wait_budget() > 30

    thread.settings = SimpleNamespace(post_data_max_retries=50)
    assert thread._worker_wait_budget() <= 600  # but never unbounded
