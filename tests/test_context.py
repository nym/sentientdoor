"""
Tests for the context block builder (firmware/context.py).

Verifies that the output format exactly matches the spec in the persona prompts.
"""

import pytest
from unittest.mock import patch
from context import build_context_block, _knock_pattern_str
from state import DoorState
from events import (
    DoorEvent,
    KNOCK_PATTERN, OPEN_GENTLE, CLOSE_GENTLE, SLAM,
    PROXIMITY_APPROACH,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_state(**overrides):
    """Return a minimal DoorState with optional attribute overrides."""
    s = DoorState()
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def make_event(kind=OPEN_GENTLE, touch_force=None, knock_pattern=None):
    return DoorEvent(kind, touch_force=touch_force, knock_pattern=knock_pattern)


def parse_block(block):
    """Parse the context block into a dict for easy assertion."""
    lines = block.strip().splitlines()
    # Strip the ``` fences
    assert lines[0] == "```"
    assert lines[-1] == "```"
    result = {}
    for line in lines[1:-1]:
        key, _, value = line.partition(": ")
        result[key.strip()] = value.strip()
    return result


# ── Structure ─────────────────────────────────────────────────────────────────

class TestStructure:

    def test_block_starts_and_ends_with_fences(self):
        s = make_state()
        block = build_context_block(s, make_event())
        lines = block.splitlines()
        assert lines[0] == "```"
        assert lines[-1] == "```"

    def test_all_required_keys_present(self):
        s = make_state()
        block = build_context_block(s, make_event())
        parsed = parse_block(block)
        required = [
            "STATE", "DURATION", "LAST_CONTACT", "IGNORED_STREAK",
            "LAST_EVENT", "TOUCH_FORCE", "OPEN_DURATION", "KNOCK_PATTERN",
            "SESSION_OPENS", "SESSION_TOUCHES", "ACCELEROMETER_NOTE",
            "TIME_OF_DAY", "DAY_OF_WEEK", "QUEUED_THOUGHT",
        ]
        for key in required:
            assert key in parsed, f"Missing key: {key}"

    def test_key_count_is_exactly_fourteen(self):
        s = make_state()
        block = build_context_block(s, make_event())
        parsed = parse_block(block)
        assert len(parsed) == 14


# ── State fields ──────────────────────────────────────────────────────────────

class TestStateFields:

    def test_state_open(self):
        s = make_state()
        s.update(DoorEvent(OPEN_GENTLE))
        block = build_context_block(s, make_event(OPEN_GENTLE))
        assert parse_block(block)["STATE"] == "open"

    def test_state_closed(self):
        s = make_state()
        block = build_context_block(s, make_event())
        assert parse_block(block)["STATE"] == "closed"

    def test_ignored_streak_reflected(self):
        s = make_state()
        s.ignored_streak = 7
        block = build_context_block(s, make_event())
        assert parse_block(block)["IGNORED_STREAK"] == "7"

    def test_session_opens_reflected(self):
        s = make_state()
        s.session_opens = 3
        block = build_context_block(s, make_event())
        assert parse_block(block)["SESSION_OPENS"] == "3"

    def test_session_touches_reflected(self):
        s = make_state()
        s.session_touches = 12
        block = build_context_block(s, make_event())
        assert parse_block(block)["SESSION_TOUCHES"] == "12"

    def test_accel_note_reflected(self):
        s = make_state()
        s.last_accel_note = "sharp impact 4.2g — slam"
        block = build_context_block(s, make_event())
        assert parse_block(block)["ACCELEROMETER_NOTE"] == "sharp impact 4.2g — slam"

    def test_accel_note_defaults_to_none_string(self):
        s = make_state()
        block = build_context_block(s, make_event())
        assert parse_block(block)["ACCELEROMETER_NOTE"] == "none"


# ── Event fields ──────────────────────────────────────────────────────────────

class TestEventFields:

    def test_last_event_reflected(self):
        s = make_state()
        event = make_event(PROXIMITY_APPROACH)
        block = build_context_block(s, event)
        assert parse_block(block)["LAST_EVENT"] == "proximity_approach"

    def test_touch_force_reflected(self):
        s = make_state()
        event = make_event(touch_force="rough")
        block = build_context_block(s, event)
        assert parse_block(block)["TOUCH_FORCE"] == "rough"

    def test_touch_force_defaults_to_na(self):
        s = make_state()
        event = make_event(touch_force=None)
        block = build_context_block(s, event)
        assert parse_block(block)["TOUCH_FORCE"] == "n/a"

    def test_open_duration_shown_on_close_gentle(self):
        s = make_state()
        s.last_open_duration = 90   # 1m 30s
        event = make_event(CLOSE_GENTLE)
        block = build_context_block(s, event)
        assert parse_block(block)["OPEN_DURATION"] == "1m 30s"

    def test_open_duration_shown_on_slam(self):
        s = make_state()
        s.last_open_duration = 5
        event = make_event(SLAM)
        block = build_context_block(s, event)
        assert parse_block(block)["OPEN_DURATION"] == "5s"

    def test_open_duration_na_on_non_close_event(self):
        s = make_state()
        s.last_open_duration = 30
        event = make_event(OPEN_GENTLE)
        block = build_context_block(s, event)
        assert parse_block(block)["OPEN_DURATION"] == "n/a"


# ── Knock pattern field ───────────────────────────────────────────────────────

class TestKnockPatternField:

    def test_knock_pattern_none_when_no_pattern(self):
        s = make_state()
        event = make_event(knock_pattern=None)
        block = build_context_block(s, event)
        assert parse_block(block)["KNOCK_PATTERN"] == "none"

    def test_knock_pattern_bucketed_and_raw(self):
        s = make_state()
        event = make_event(KNOCK_PATTERN, knock_pattern=[150, 300, 600, 150])
        block = build_context_block(s, event)
        value = parse_block(block)["KNOCK_PATTERN"]
        # Buckets: 150→1, 300→2, 600→3, 150→1
        assert value.startswith("1-2-3-1")
        # Raw ms values also present
        assert "150" in value
        assert "300" in value
        assert "600" in value


class TestKnockPatternStr:

    def test_empty_returns_none(self):
        assert _knock_pattern_str([]) == "none"

    def test_short_intervals_bucket_to_1(self):
        result = _knock_pattern_str([100, 150, 199])
        assert result.startswith("1-1-1")

    def test_medium_intervals_bucket_to_2(self):
        result = _knock_pattern_str([200, 300, 449])
        assert result.startswith("2-2-2")

    def test_long_intervals_bucket_to_3(self):
        result = _knock_pattern_str([450, 600, 800])
        assert result.startswith("3-3-3")

    def test_boundary_200ms_is_medium(self):
        result = _knock_pattern_str([200])
        assert result.startswith("2")

    def test_boundary_450ms_is_long(self):
        result = _knock_pattern_str([450])
        assert result.startswith("3")

    def test_raw_ms_appended(self):
        result = _knock_pattern_str([200, 400])
        assert "200" in result
        assert "400" in result


# ── Queued thought ────────────────────────────────────────────────────────────

class TestQueuedThought:

    def test_queued_thought_included(self):
        s = make_state()
        block = build_context_block(s, make_event(), queued_thought="Something is different today.")
        assert parse_block(block)["QUEUED_THOUGHT"] == "Something is different today."

    def test_empty_queued_thought_is_blank(self):
        s = make_state()
        block = build_context_block(s, make_event(), queued_thought="")
        assert parse_block(block)["QUEUED_THOUGHT"] == ""

    def test_default_queued_thought_is_blank(self):
        s = make_state()
        block = build_context_block(s, make_event())
        assert parse_block(block)["QUEUED_THOUGHT"] == ""


# ── Time fields ───────────────────────────────────────────────────────────────

class TestTimeFields:

    @pytest.mark.parametrize("hour,expected", [
        (5,  "morning"),
        (11, "morning"),
        (12, "afternoon"),
        (16, "afternoon"),
        (17, "evening"),
        (21, "evening"),
        (22, "night"),
        (4,  "night"),
    ])
    def test_time_of_day(self, hour, expected):
        import time
        fake_struct = time.struct_time((2026, 3, 21, hour, 0, 0, 5, 80, 0))
        with patch("context.time.localtime", return_value=fake_struct):
            s = make_state()
            block = build_context_block(s, make_event())
        assert parse_block(block)["TIME_OF_DAY"] == expected

    @pytest.mark.parametrize("wday,expected", [
        (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"),
        (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
    ])
    def test_day_of_week(self, wday, expected):
        import time
        fake_struct = time.struct_time((2026, 3, 21, 10, 0, 0, wday, 80, 0))
        with patch("context.time.localtime", return_value=fake_struct):
            s = make_state()
            block = build_context_block(s, make_event())
        assert parse_block(block)["DAY_OF_WEEK"] == expected
