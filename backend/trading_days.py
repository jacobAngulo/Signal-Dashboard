"""Forward trading-session arithmetic for signal windows and exit dates.

`Store.trading_calendar()` (backend/store.py) is built from dates the daily
producers have actually scored -- it is observed history only and cannot name
a session that hasn't happened yet ("this 126-session window closes on ...").
This module builds a real XNYS session calendar via the `exchange-calendars`
package, lazily and once, and caches it in a module global.

Fail soft, always. A missing exit *date* must never take the dashboard down:
the window column and the raw session counts already render from data held in
memory, and only the fully-optional "closes on ..." string depends on this
module working at all. So every function here returns None on any failure --
import, calendar build, or a bad date -- rather than raising, and the app
starts and serves normally either way.
"""
from datetime import date, timedelta

_calendar_built = False
_calendar = None


def _get_calendar():
    """Build (once) and cache the XNYS session calendar. None on any failure."""
    global _calendar_built, _calendar
    if _calendar_built:
        return _calendar
    _calendar_built = True
    try:
        # Imported here, not at module scope, so importing this module stays
        # cheap even when exchange-calendars is missing or slow to build.
        import exchange_calendars as xcals

        end = (date.today() + timedelta(days=365 * 3)).isoformat()
        _calendar = xcals.get_calendar("XNYS", start="2015-01-01", end=end)
    except Exception:
        _calendar = None
    return _calendar


def session_offset(date_str, n):
    """The session `n` XNYS trading sessions after `date_str`, or None.

    `date_str` need not itself be an exact session -- it snaps forward to the
    next one first, matching how the rest of the app treats a signal date.
    """
    cal = _get_calendar()
    if cal is None or date_str is None or n is None:
        return None
    try:
        session = cal.date_to_session(date_str, direction="next")
        offset = cal.session_offset(session, int(n))
        return offset.date().isoformat()
    except Exception:
        return None


def sessions_between(start, end):
    """Count of XNYS sessions strictly after `start`, through `end`.

    None if either date is missing or the calendar is unavailable. Exclusive
    of `start` (a `start == end` range is 0 sessions elapsed).
    """
    cal = _get_calendar()
    if cal is None or start is None or end is None:
        return None
    try:
        return cal.sessions_distance(start, end) - 1
    except Exception:
        return None


def is_session(date_str):
    """Whether `date_str` is an XNYS trading session. None if unknown."""
    cal = _get_calendar()
    if cal is None or date_str is None:
        return None
    try:
        return bool(cal.is_session(date_str))
    except Exception:
        return None
