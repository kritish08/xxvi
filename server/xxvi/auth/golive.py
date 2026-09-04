from datetime import UTC, datetime

from xxvi.settings import Settings


def go_live_instant(settings: Settings) -> datetime:
    """The configured go-live moment, normalised to UTC.

    Configured as an IST wall-clock time. Stored and compared as a UTC
    instant so the server's own timezone is never load-bearing.
    """
    parsed = datetime.fromisoformat(settings.go_live_iso)
    if parsed.tzinfo is None:
        raise ValueError("go_live_iso must carry an explicit UTC offset")
    return parsed.astimezone(UTC)


def is_live(now: datetime, settings: Settings, *, forced: bool) -> bool:
    if forced:
        return True
    return now >= go_live_instant(settings)


def seconds_until_live(now: datetime, settings: Settings) -> int:
    remaining = (go_live_instant(settings) - now).total_seconds()
    return max(0, int(remaining))
