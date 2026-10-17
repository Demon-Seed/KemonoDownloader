"""Shared retry timing for API and post-data requests.

The retry waits used to be either an uncapped exponential backoff
(``2 ** attempt``) or a flat five second countdown on every attempt.  With
``api_request_max_retries`` accepting values up to 50, the exponential
schedule could grow into years of sleeping, while non-200 responses were
retried with no delay at all.  These helpers keep the waits short,
monotonic and hard capped.
"""

from typing import Optional

# Delay before the second API attempt; grows by one second per attempt.
API_RETRY_BASE_DELAY = 1.0
# Hard ceiling for a single API retry wait.
API_RETRY_MAX_DELAY = 4.0
# Upper bound for a server supplied Retry-After value.
RETRY_AFTER_CAP = 30.0
# Hard ceiling for the "Trying again in N..." post-data countdown.
COUNTDOWN_MAX_SECONDS = 5

# Statuses where retrying cannot help: the request itself is wrong.
TERMINAL_STATUS_CODES = frozenset({400, 401, 402, 404, 405, 406, 410, 451})


def is_terminal_status(status_code) -> bool:
    """Return True when *status_code* should not be retried at all."""
    try:
        return int(status_code) in TERMINAL_STATUS_CODES
    except (TypeError, ValueError):
        return False


def retry_after_seconds(response) -> Optional[float]:
    """Return the server's Retry-After value in seconds, if it sent one."""
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        raw = headers.get("Retry-After")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        # The HTTP-date form is not sent by these APIs; ignore it.
        return None
    if value < 0:
        return None
    return min(value, RETRY_AFTER_CAP)


def api_retry_delay(attempt: int, response=None) -> float:
    """Seconds to wait after API *attempt* (zero based) failed.

    Linear ramp (1, 2, 3, 4) capped at :data:`API_RETRY_MAX_DELAY`, so a
    high retry count can no longer escalate without bound.  A server
    supplied ``Retry-After`` wins, bounded by :data:`RETRY_AFTER_CAP`.
    """
    requested = retry_after_seconds(response)
    if requested is not None:
        return requested
    try:
        index = max(int(attempt), 0)
    except (TypeError, ValueError):
        index = 0
    return min(API_RETRY_BASE_DELAY + index, API_RETRY_MAX_DELAY)


def countdown_seconds(attempt: int, base: int = 2) -> int:
    """Length of the post-data countdown before retry number *attempt*.

    *base* is the first wait (2 seconds by default, replacing the old flat
    5 seconds); each later retry adds a second up to
    :data:`COUNTDOWN_MAX_SECONDS`.  ``base=0`` disables the countdown
    entirely, which tests rely on to skip the wait.
    """
    try:
        base_value = max(int(base), 0)
        index = max(int(attempt), 1)
    except (TypeError, ValueError):
        base_value, index = 2, 1
    if base_value == 0:
        return 0
    # Never shorten a base the caller asked for explicitly.
    cap = max(COUNTDOWN_MAX_SECONDS, base_value)
    return min(base_value + index - 1, cap)
