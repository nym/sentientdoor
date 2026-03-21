"""
Knock pattern recogniser.

Listens to a stream of KNOCK_SOFT / KNOCK_LOUD events and decides whether
a sequence of 5–8 knocks constitutes a deliberate pattern knock vs. random
noise.

A "pattern knock" is defined as:
  - Between KNOCK_PATTERN_MIN and KNOCK_PATTERN_MAX individual knocks
  - Each inter-knock gap <= KNOCK_WINDOW_MS
  - The sequence ends when a gap > KNOCK_WINDOW_MS is observed

Once a pattern is confirmed, a KNOCK_PATTERN event is emitted carrying:
  - knock_pattern: list of inter-note intervals (ms)  ← e.g. [200, 180, 400, 180, 200]
  - accel_note: compact representation, e.g. "5-note: 200-180-400-180-200"

The recogniser also keeps a rolling memory of the last 8 confirmed patterns
(as lists of intervals) so the context builder can report whether the current
knock matches a familiar sequence.

Usage
-----
    recogniser = KnockRecogniser(settings)

    # In the event loop, feed raw knock events:
    pattern_event = recogniser.feed(raw_knock_event)
    if pattern_event:
        queue.put(pattern_event)
"""

import time
from events import DoorEvent, KNOCK_SOFT, KNOCK_LOUD, KNOCK_PATTERN


class KnockRecogniser:

    def __init__(self, settings):
        self._window_ms = int(settings.get("KNOCK_WINDOW_MS", 800))
        self._min_notes = int(settings.get("KNOCK_PATTERN_MIN", 5))
        self._max_notes = int(settings.get("KNOCK_PATTERN_MAX", 8))

        self._buffer = []          # list of (monotonic_s, DoorEvent)
        self._last_knock_time = None

        # Rolling history of confirmed patterns (lists of int intervals in ms)
        self._known_patterns = []
        self._known_pattern_maxlen = 8

    # ── Public interface ──────────────────────────────────────────────────────

    def feed(self, event):
        """
        Feed a raw knock event. Returns a KNOCK_PATTERN DoorEvent if a
        complete pattern has just been recognised, otherwise None.

        Call this before putting the raw event on the main queue — if a
        pattern is returned, put the pattern event instead (or as well,
        depending on desired behaviour).
        """
        if event.kind not in (KNOCK_SOFT, KNOCK_LOUD):
            return None

        now_ms = int(time.monotonic() * 1000)

        if self._last_knock_time is not None:
            gap = now_ms - self._last_knock_time
            if gap > self._window_ms:
                # Gap too long — flush whatever we had, start fresh
                pattern_event = self._try_emit()
                self._buffer = []
                self._buffer.append((now_ms, event))
                self._last_knock_time = now_ms
                return pattern_event

        self._buffer.append((now_ms, event))
        self._last_knock_time = now_ms

        # If we've hit the max, emit immediately
        if len(self._buffer) >= self._max_notes:
            pattern_event = self._try_emit()
            self._buffer = []
            self._last_knock_time = None
            return pattern_event

        return None

    def flush(self):
        """
        Call periodically (e.g. every KNOCK_WINDOW_MS) to emit any pattern
        that has been silently completed (no further knock to trigger the gap
        check). Returns a DoorEvent or None.
        """
        if not self._buffer:
            return None
        if self._last_knock_time is None:
            return None
        now_ms = int(time.monotonic() * 1000)
        if now_ms - self._last_knock_time >= self._window_ms:
            event = self._try_emit()
            self._buffer = []
            self._last_knock_time = None
            return event
        return None

    @property
    def known_patterns(self):
        """List of previously seen interval sequences (list of list of int)."""
        return list(self._known_patterns)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _try_emit(self):
        """If the buffer meets the length threshold, return a KNOCK_PATTERN event."""
        if len(self._buffer) < self._min_notes:
            return None

        times = [t for t, _ in self._buffer]
        intervals = [times[i+1] - times[i] for i in range(len(times) - 1)]
        n = len(self._buffer)

        # Check familiarity
        familiar = self._is_familiar(intervals)

        # Record in history
        self._remember(intervals)

        # Build a compact string: "5-note: 200-180-400-180-200"
        interval_str = "-".join(str(ms) for ms in intervals)
        note_str = f"{n}-note: {interval_str}"
        if familiar:
            note_str += " (recognised)"

        accel_note = note_str

        return DoorEvent(
            KNOCK_PATTERN,
            accel_note=accel_note,
            knock_pattern=intervals,
        )

    def _remember(self, intervals):
        if intervals not in self._known_patterns:
            self._known_patterns.append(intervals)
            if len(self._known_patterns) > self._known_pattern_maxlen:
                self._known_patterns.pop(0)

    def _is_familiar(self, intervals, tolerance_ms=120):
        """
        Returns True if `intervals` is within tolerance of any known pattern.
        Tolerance is per-interval absolute difference.
        """
        for known in self._known_patterns:
            if len(known) != len(intervals):
                continue
            if all(abs(a - b) <= tolerance_ms for a, b in zip(intervals, known)):
                return True
        return False
