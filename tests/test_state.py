"""
Tests for the door state machine (firmware/state.py).
"""

import pytest
from unittest.mock import patch
from state import DoorState, _fmt_duration
from events import (
    DoorEvent,
    KNOCK_SOFT, KNOCK_LOUD, KNOCK_PATTERN,
    OPEN_GENTLE, OPEN_FORCE, CLOSE_GENTLE, SLAM,
    TOUCH_GENTLE, TOUCH_ROUGH, LEAN,
    PROXIMITY_APPROACH, PROXIMITY_DEPART,
)


def ev(kind, peak_g=0.0, touch_force=None, accel_note="", knock_pattern=None):
    return DoorEvent(kind, peak_g=peak_g, touch_force=touch_force,
                     accel_note=accel_note, knock_pattern=knock_pattern)


# ── Duration formatting ───────────────────────────────────────────────────────

class TestFmtDuration:

    def test_seconds_only(self):
        assert _fmt_duration(45) == "45s"

    def test_exactly_one_minute(self):
        assert _fmt_duration(60) == "1m 0s"

    def test_minutes_and_seconds(self):
        assert _fmt_duration(125) == "2m 5s"

    def test_exactly_one_hour(self):
        assert _fmt_duration(3600) == "1h 0m"

    def test_hours_and_minutes(self):
        assert _fmt_duration(3723) == "1h 2m"

    def test_zero(self):
        assert _fmt_duration(0) == "0s"

    def test_float_truncated(self):
        assert _fmt_duration(59.9) == "59s"


# ── Open / closed state ───────────────────────────────────────────────────────

class TestOpenClosed:

    def test_starts_closed(self):
        s = DoorState()
        assert s.is_open is False
        assert s.state_label == "closed"

    def test_open_gentle_sets_open(self):
        s = DoorState()
        s.update(ev(OPEN_GENTLE))
        assert s.is_open is True
        assert s.state_label == "open"

    def test_open_force_sets_open(self):
        s = DoorState()
        s.update(ev(OPEN_FORCE))
        assert s.is_open is True

    def test_close_gentle_sets_closed(self):
        s = DoorState()
        s.update(ev(OPEN_GENTLE))
        s.update(ev(CLOSE_GENTLE))
        assert s.is_open is False

    def test_slam_sets_closed(self):
        s = DoorState()
        s.update(ev(OPEN_GENTLE))
        s.update(ev(SLAM))
        assert s.is_open is False

    def test_last_open_duration_recorded_on_close(self):
        s = DoorState()
        with patch("state.time.monotonic", return_value=0.0):
            s.update(ev(OPEN_GENTLE))
        with patch("state.time.monotonic", return_value=30.0):
            s.update(ev(CLOSE_GENTLE))
        assert s.last_open_duration == pytest.approx(30.0, abs=0.1)

    def test_last_open_duration_none_if_closed_without_opening(self):
        s = DoorState()
        s.update(ev(CLOSE_GENTLE))
        assert s.last_open_duration is None

    def test_open_duration_str_unknown_before_first_close(self):
        s = DoorState()
        assert s.last_open_duration_str == "unknown"


# ── Session counters ──────────────────────────────────────────────────────────

class TestSessionCounters:

    def test_session_opens_increments_on_open(self):
        s = DoorState()
        s.update(ev(OPEN_GENTLE))
        s.update(ev(CLOSE_GENTLE))
        s.update(ev(OPEN_FORCE))
        assert s.session_opens == 2

    def test_session_slams_increments_on_slam_only(self):
        s = DoorState()
        s.update(ev(OPEN_GENTLE))
        s.update(ev(SLAM))
        s.update(ev(OPEN_GENTLE))
        s.update(ev(CLOSE_GENTLE))   # not a slam
        assert s.session_slams == 1

    def test_session_touches_increments_for_touch_events(self):
        s = DoorState()
        for kind in (TOUCH_GENTLE, TOUCH_ROUGH, KNOCK_SOFT, KNOCK_LOUD, LEAN):
            s.update(ev(kind))
        assert s.session_touches == 5

    def test_open_close_do_not_increment_touches(self):
        s = DoorState()
        s.update(ev(OPEN_GENTLE))
        s.update(ev(CLOSE_GENTLE))
        assert s.session_touches == 0

    def test_knock_pattern_increments_touches(self):
        s = DoorState()
        s.update(ev(KNOCK_PATTERN, knock_pattern=[200, 200, 200, 200]))
        assert s.session_touches == 1


# ── Ignored streak ────────────────────────────────────────────────────────────

class TestIgnoredStreak:

    def test_starts_at_zero(self):
        assert DoorState().ignored_streak == 0

    def test_approach_then_depart_without_interaction_increments_streak(self):
        s = DoorState()
        s.update(ev(PROXIMITY_APPROACH))
        s.update(ev(PROXIMITY_DEPART))
        assert s.ignored_streak == 1

    def test_three_ignores_streak_is_three(self):
        s = DoorState()
        for _ in range(3):
            s.update(ev(PROXIMITY_APPROACH))
            s.update(ev(PROXIMITY_DEPART))
        assert s.ignored_streak == 3

    def test_interaction_before_depart_breaks_streak(self):
        s = DoorState()
        # First person ignored
        s.update(ev(PROXIMITY_APPROACH))
        s.update(ev(PROXIMITY_DEPART))
        assert s.ignored_streak == 1

        # Second person interacts — streak resets
        s.update(ev(PROXIMITY_APPROACH))
        s.update(ev(KNOCK_SOFT))
        s.update(ev(PROXIMITY_DEPART))
        assert s.ignored_streak == 0

    def test_open_during_visit_counts_as_interaction(self):
        s = DoorState()
        s.update(ev(PROXIMITY_APPROACH))
        s.update(ev(OPEN_GENTLE))
        s.update(ev(PROXIMITY_DEPART))
        assert s.ignored_streak == 0

    def test_lean_counts_as_interaction(self):
        s = DoorState()
        s.update(ev(PROXIMITY_APPROACH))
        s.update(ev(LEAN))
        s.update(ev(PROXIMITY_DEPART))
        assert s.ignored_streak == 0

    def test_streak_resumes_after_reset(self):
        s = DoorState()
        s.update(ev(PROXIMITY_APPROACH))
        s.update(ev(PROXIMITY_DEPART))   # streak = 1
        s.update(ev(PROXIMITY_APPROACH))
        s.update(ev(KNOCK_SOFT))
        s.update(ev(PROXIMITY_DEPART))   # interaction → streak = 0
        s.update(ev(PROXIMITY_APPROACH))
        s.update(ev(PROXIMITY_DEPART))   # ignored again → streak = 1
        assert s.ignored_streak == 1


# ── Grip sample history ───────────────────────────────────────────────────────

class TestGripSamples:

    def test_grip_recorded_on_nonzero_peak(self):
        s = DoorState()
        s.update(ev(KNOCK_SOFT, peak_g=1.5))
        assert 1.5 in s._grip_samples

    def test_zero_peak_not_recorded(self):
        s = DoorState()
        s.update(ev(KNOCK_SOFT, peak_g=0.0))
        assert s._grip_samples == []

    def test_rolling_window_capped_at_20(self):
        s = DoorState()
        for i in range(25):
            s.update(ev(KNOCK_SOFT, peak_g=float(i)))
        assert len(s._grip_samples) == 20
        # Most recent values retained
        assert s._grip_samples[-1] == 24.0

    def test_grip_summary_no_data(self):
        assert DoorState().grip_summary == "no grip data"

    def test_grip_summary_with_data(self):
        s = DoorState()
        s.update(ev(KNOCK_SOFT, peak_g=1.0))
        s.update(ev(KNOCK_SOFT, peak_g=3.0))
        summary = s.grip_summary
        assert "avg" in summary
        assert "peak" in summary


# ── Knock pattern mirroring ───────────────────────────────────────────────────

class TestKnockPattern:

    def test_last_knock_pattern_stored(self):
        s = DoorState()
        s.update(ev(KNOCK_PATTERN, knock_pattern=[200, 300, 200]))
        assert s.last_knock_pattern == [200, 300, 200]

    def test_set_known_patterns(self):
        s = DoorState()
        patterns = [[200, 200, 200, 200], [300, 150, 300]]
        s.set_known_patterns(patterns)
        assert s.known_knock_patterns == patterns


# ── Last contact ──────────────────────────────────────────────────────────────

class TestLastContact:

    def test_never_before_any_event(self):
        s = DoorState()
        assert s.last_contact_str == "never"

    def test_contact_updated_on_knock(self):
        s = DoorState()
        with patch("state.time.monotonic", return_value=1000.0):
            s.update(ev(KNOCK_SOFT))
        with patch("state.time.monotonic", return_value=1045.0):
            result = s.last_contact_str
        assert result == "45s"

    def test_proximity_approach_alone_does_not_set_contact(self):
        s = DoorState()
        s.update(ev(PROXIMITY_APPROACH))
        assert s.last_contact_str == "never"

    def test_proximity_depart_does_not_set_contact(self):
        s = DoorState()
        s.update(ev(PROXIMITY_DEPART))
        assert s.last_contact_str == "never"
