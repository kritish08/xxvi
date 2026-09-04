from datetime import UTC, datetime, timedelta, timezone

from xxvi.auth.golive import go_live_instant, is_live, seconds_until_live
from xxvi.settings import Settings

SETTINGS = Settings(go_live_iso="2026-08-20T00:00:00+05:30")


def test_ist_midnight_resolves_to_the_expected_utc_instant():
    # 00:00 on 20 Aug in Asia/Kolkata is 18:30 on 19 Aug UTC.
    assert go_live_instant(SETTINGS) == datetime(2026, 8, 19, 18, 30, tzinfo=UTC)


def test_go_live_instant_is_explicitly_utc_normalised():
    # Equality between aware datetimes compares the instant regardless of
    # tzinfo, so the test above alone would not catch a missing
    # `.astimezone(UTC)`. The interface promises a UTC-aware value, so
    # pin the tzinfo itself.
    assert go_live_instant(SETTINGS).tzinfo == UTC


def test_gate_holds_one_minute_before():
    one_minute_early = datetime(2026, 8, 19, 18, 29, tzinfo=UTC)
    assert is_live(one_minute_early, SETTINGS, forced=False) is False


def test_gate_opens_one_minute_after():
    one_minute_late = datetime(2026, 8, 19, 18, 31, tzinfo=UTC)
    assert is_live(one_minute_late, SETTINGS, forced=False) is True


def test_gate_opens_exactly_on_the_instant():
    assert is_live(go_live_instant(SETTINGS), SETTINGS, forced=False) is True


def test_force_unlock_overrides_a_closed_gate():
    long_before = datetime(2026, 1, 1, tzinfo=UTC)
    assert is_live(long_before, SETTINGS, forced=True) is True


def test_countdown_is_reported_in_whole_seconds_and_floors_at_zero():
    now = go_live_instant(SETTINGS) - timedelta(seconds=90)
    assert seconds_until_live(now, SETTINGS) == 90
    assert seconds_until_live(go_live_instant(SETTINGS), SETTINGS) == 0
    assert seconds_until_live(datetime(2027, 1, 1, tzinfo=UTC), SETTINGS) == 0


def test_go_live_instant_rejects_naive_datetime():
    naive_settings = Settings(go_live_iso="2026-08-20T00:00:00")
    try:
        go_live_instant(naive_settings)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for naive go_live_iso")


def test_is_live_boundary_one_second_before_gate_is_closed():
    one_second_early = go_live_instant(SETTINGS) - timedelta(seconds=1)
    assert is_live(one_second_early, SETTINGS, forced=False) is False


def test_go_live_instant_resolves_correctly_at_utc_offset():
    # Every other test in this file uses +05:30. A mutation that hardcodes
    # "treat the wall clock as IST" instead of using the parsed offset
    # would still pass all of those. Pin a config at +00:00: here the
    # wall-clock value and the UTC instant are numerically identical, so
    # a hardcoded-IST-shift bug would visibly offset the result.
    utc_settings = Settings(go_live_iso="2026-08-20T00:00:00+00:00")
    assert go_live_instant(utc_settings) == datetime(2026, 8, 20, 0, 0, tzinfo=UTC)


def test_go_live_instant_resolves_correctly_at_negative_offset():
    # A hardcoded-IST-shift bug applied to a -08:00 config would be off
    # by roughly 13.5 hours, not just wrong by a few minutes, so this is
    # a sharp check on genuine offset-independence.
    pst_settings = Settings(go_live_iso="2026-08-20T00:00:00-08:00")
    assert go_live_instant(pst_settings) == datetime(2026, 8, 20, 8, 0, tzinfo=UTC)


def test_is_live_accepts_a_now_labelled_in_a_non_utc_offset():
    # Every other is_live test in this file passes a UTC-labelled `now`.
    # A mutation that strips tzinfo and compares wall-clock values
    # naively (instead of relying on Python's aware-datetime instant
    # comparison) would survive all of them. One minute after go-live,
    # expressed in UTC, is 2026-08-19T18:31:00+00:00; the same instant
    # labelled -08:00 is 2026-08-19T10:31:00-08:00.
    one_minute_late_as_pst = datetime(2026, 8, 19, 10, 31, tzinfo=timezone(timedelta(hours=-8)))
    assert is_live(one_minute_late_as_pst, SETTINGS, forced=False) is True
