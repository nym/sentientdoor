"""
Tests for the knock pattern recogniser (firmware/knock.py).

Time is controlled via unittest.mock.patch so every test is deterministic —
no real sleeping.
"""

import pytest
from unittest.mock import patch
from knock import KnockRecogniser
from events import KNOCK_SOFT, KNOCK_LOUD, KNOCK_PATTERN, DoorEvent


# ── Helpers ───────────────────────────────────────────────────────────────────

SETTINGS = {
    "KNOCK_WINDOW_MS": "800",
    "KNOCK_PATTERN_MIN": "5",
    "KNOCK_PATTERN_MAX": "8",
}


def rec(settings=None):
    return KnockRecogniser(settings or SETTINGS)


def knock(t_ms, kind=KNOCK_SOFT):
    """Return a fake knock event with time.monotonic patched to t_ms/1000."""
    return (t_ms, DoorEvent(kind, peak_g=1.5))


def feed_sequence(recogniser, knocks):
    """
    Feed a list of (t_ms, event) tuples into the recogniser, patching
    time.monotonic to the given time for each call.
    Returns the list of non-None results (pattern events).
    """
    results = []
    for t_ms, event in knocks:
        with patch("knock.time.monotonic", return_value=t_ms / 1000.0):
            result = recogniser.feed(event)
        if result is not None:
            results.append(result)
    return results


def flush_at(recogniser, t_ms):
    with patch("knock.time.monotonic", return_value=t_ms / 1000.0):
        return recogniser.flush()


# ── Basic emission ────────────────────────────────────────────────────────────

class TestBasicEmission:

    def test_fewer_than_min_notes_emits_nothing_on_gap(self):
        r = rec()
        knocks = [knock(t) for t in [0, 200, 400, 600]]   # only 4 notes
        results = feed_sequence(r, knocks)
        # Trigger a gap to flush the buffer
        results += feed_sequence(r, [knock(600 + 900)])    # gap > 800ms
        assert results == []

    def test_exactly_min_notes_emits_on_long_gap(self):
        r = rec()
        # 5 notes spaced 200ms apart, then a 900ms gap
        times = [i * 200 for i in range(5)]
        results = feed_sequence(r, [knock(t) for t in times])
        # Should be nothing yet — gap hasn't been observed
        assert results == []

        # Now a note after a long gap triggers flush of the buffer
        results = feed_sequence(r, [knock(times[-1] + 900)])
        assert len(results) == 1
        assert results[0].kind == KNOCK_PATTERN

    def test_exactly_min_notes_emitted_on_flush(self):
        r = rec()
        times = [i * 200 for i in range(5)]
        feed_sequence(r, [knock(t) for t in times])

        # flush() at t > last_knock + window
        event = flush_at(r, times[-1] + 900)
        assert event is not None
        assert event.kind == KNOCK_PATTERN

    def test_exactly_max_notes_emits_immediately(self):
        r = rec()
        times = [i * 100 for i in range(8)]   # 8 notes
        results = feed_sequence(r, [knock(t) for t in times])
        assert len(results) == 1
        assert results[0].kind == KNOCK_PATTERN

    def test_more_than_max_splits_into_two_sequences(self):
        r = rec()
        # 9 rapid knocks: first 8 emit immediately, 9th starts a new buffer
        times = [i * 100 for i in range(9)]
        results = feed_sequence(r, [knock(t) for t in times])
        # First batch of 8 emits at note 8
        assert len(results) == 1
        assert results[0].kind == KNOCK_PATTERN
        # 9th note is now sitting in a new buffer — no second emit yet
        event = flush_at(r, times[-1] + 900)
        # Only 1 note in new buffer — below min, so flush emits nothing
        assert event is None


# ── Interval content ──────────────────────────────────────────────────────────

class TestIntervalContent:

    def test_intervals_match_timing(self):
        r = rec()
        times = [0, 200, 500, 700, 1000, 1300]   # 6 notes
        feed_sequence(r, [knock(t) for t in times])
        event = flush_at(r, 1300 + 900)

        assert event is not None
        expected = [200, 300, 200, 300, 300]
        assert event.knock_pattern == expected

    def test_accel_note_contains_note_count(self):
        r = rec()
        times = [i * 200 for i in range(5)]
        feed_sequence(r, [knock(t) for t in times])
        event = flush_at(r, times[-1] + 900)

        assert "5-note" in event.accel_note

    def test_accel_note_contains_intervals(self):
        r = rec()
        times = [0, 250, 500, 750, 1000]
        feed_sequence(r, [knock(t) for t in times])
        event = flush_at(r, 1000 + 900)

        assert "250" in event.accel_note

    def test_mixed_soft_and_loud_knocks_accepted(self):
        r = rec()
        kinds = [KNOCK_SOFT, KNOCK_LOUD, KNOCK_SOFT, KNOCK_LOUD, KNOCK_SOFT]
        knocks_seq = [(i * 200, DoorEvent(k, peak_g=1.5)) for i, k in enumerate(kinds)]
        feed_sequence(r, knocks_seq)
        event = flush_at(r, 4 * 200 + 900)
        assert event is not None
        assert event.kind == KNOCK_PATTERN


# ── Window / gap behaviour ────────────────────────────────────────────────────

class TestWindowBehaviour:

    def test_gap_exactly_at_window_is_not_a_break(self):
        # gap == window_ms (800) should still be within the window
        r = rec()
        times = [0, 200, 400, 600, 800, 800 + 800]   # 6th knock at exactly window boundary
        results = feed_sequence(r, [knock(t) for t in times])
        # No emit expected yet (gap == window, not strictly greater)
        assert results == []

    def test_gap_one_ms_over_window_triggers_flush(self):
        r = rec()
        times = [i * 200 for i in range(5)]
        feed_sequence(r, [knock(t) for t in times])
        results = feed_sequence(r, [knock(times[-1] + 801)])
        assert len(results) == 1

    def test_non_knock_events_are_ignored(self):
        from events import OPEN_GENTLE
        r = rec()
        non_knock = DoorEvent(OPEN_GENTLE)
        with patch("knock.time.monotonic", return_value=0.0):
            result = r.feed(non_knock)
        assert result is None
        # Buffer is still empty
        assert r._buffer == []

    def test_flush_before_window_expires_returns_none(self):
        r = rec()
        times = [i * 200 for i in range(5)]
        feed_sequence(r, [knock(t) for t in times])
        # Flush only 400ms after last knock — window hasn't expired
        event = flush_at(r, times[-1] + 400)
        assert event is None

    def test_flush_on_empty_buffer_returns_none(self):
        r = rec()
        event = flush_at(r, 5000)
        assert event is None


# ── Pattern memory and familiarity ────────────────────────────────────────────

class TestFamiliarity:

    def _emit_pattern(self, r, times, flush_gap=900):
        feed_sequence(r, [knock(t) for t in times])
        return flush_at(r, times[-1] + flush_gap)

    def test_first_occurrence_is_not_familiar(self):
        r = rec()
        event = self._emit_pattern(r, [0, 200, 400, 600, 800])
        assert event is not None
        assert "(recognised)" not in event.accel_note

    def test_exact_repeat_is_familiar(self):
        r = rec()
        # Emit once to register it
        self._emit_pattern(r, [0, 200, 400, 600, 800])
        # Now emit the same pattern again (offset times)
        event = self._emit_pattern(r, [2000, 2200, 2400, 2600, 2800])
        assert event is not None
        assert "(recognised)" in event.accel_note

    def test_pattern_within_tolerance_is_familiar(self):
        r = rec()
        self._emit_pattern(r, [0, 200, 400, 600, 800])
        # Each interval is 200ms; offset each by 100ms (within 120ms tolerance)
        event = self._emit_pattern(r, [2000, 2300, 2500, 2700, 2900])
        # intervals: 300, 200, 200, 200 — first differs by 100ms, within tolerance
        assert event is not None
        assert "(recognised)" in event.accel_note

    def test_pattern_outside_tolerance_is_not_familiar(self):
        r = rec()
        self._emit_pattern(r, [0, 200, 400, 600, 800])
        # Intervals heavily altered: 400ms gaps vs 200ms — delta 200ms > 120ms tolerance
        event = self._emit_pattern(r, [2000, 2400, 2800, 3200, 3600])
        assert event is not None
        assert "(recognised)" not in event.accel_note

    def test_different_length_pattern_is_not_familiar(self):
        r = rec()
        # Register a 5-note pattern
        self._emit_pattern(r, [0, 200, 400, 600, 800])
        # Emit a 6-note pattern with the same spacing
        event = self._emit_pattern(r, [2000, 2200, 2400, 2600, 2800, 3000])
        assert event is not None
        assert "(recognised)" not in event.accel_note

    def test_known_patterns_stored_after_emit(self):
        r = rec()
        self._emit_pattern(r, [0, 200, 400, 600, 800])
        assert len(r.known_patterns) == 1
        assert r.known_patterns[0] == [200, 200, 200, 200]

    def test_duplicate_pattern_not_stored_twice(self):
        r = rec()
        self._emit_pattern(r, [0, 200, 400, 600, 800])
        self._emit_pattern(r, [2000, 2200, 2400, 2600, 2800])
        assert len(r.known_patterns) == 1

    def test_rolling_memory_capped_at_eight(self):
        r = rec()
        # Emit 9 distinct patterns
        for i in range(9):
            base = i * 5000
            # Vary one interval so each pattern is unique
            times = [base, base + 200 + i * 15, base + 400 + i * 30,
                     base + 600 + i * 15, base + 800]
            self._emit_pattern(r, times)
        assert len(r.known_patterns) <= 8


# ── Custom settings ───────────────────────────────────────────────────────────

class TestCustomSettings:

    def test_custom_min_3_emits_on_3_notes(self):
        r = rec({"KNOCK_WINDOW_MS": "800", "KNOCK_PATTERN_MIN": "3", "KNOCK_PATTERN_MAX": "8"})
        times = [0, 200, 400]
        feed_sequence(r, [knock(t) for t in times])
        event = flush_at(r, 400 + 900)
        assert event is not None
        assert event.kind == KNOCK_PATTERN

    def test_custom_max_3_emits_at_3_without_gap(self):
        r = rec({"KNOCK_WINDOW_MS": "800", "KNOCK_PATTERN_MIN": "2", "KNOCK_PATTERN_MAX": "3"})
        times = [0, 200, 400]
        results = feed_sequence(r, [knock(t) for t in times])
        assert len(results) == 1

    def test_narrow_window_50ms_rejects_200ms_gaps(self):
        r = rec({"KNOCK_WINDOW_MS": "50", "KNOCK_PATTERN_MIN": "5", "KNOCK_PATTERN_MAX": "8"})
        times = [i * 200 for i in range(5)]  # 200ms gaps > 50ms window
        results = feed_sequence(r, [knock(t) for t in times])
        # Each knock arrives after a gap > window, so each flushes previous (< min) and restarts
        assert results == []
