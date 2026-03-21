"""
Door state machine and session memory.

Tracks:
  - Open / closed + duration
  - Time since last human contact
  - Ignored-person streak (consecutive approaches without interaction)
  - Session counters (opens, touches, slams)
  - Grip sample history (peak_g per interaction)
  - Known knock patterns (delegated to KnockRecogniser, mirrored here)

Consumed by context.py to build the LLM sensor block.
"""

import time
from events import (
    KNOCK_SOFT, KNOCK_LOUD, KNOCK_PATTERN,
    OPEN_GENTLE, OPEN_FORCE, CLOSE_GENTLE, SLAM,
    TOUCH_GENTLE, TOUCH_ROUGH, LEAN,
    PROXIMITY_APPROACH, PROXIMITY_DEPART,
    FORCE_GENTLE, FORCE_NORMAL, FORCE_ROUGH,
)


def _fmt_duration(seconds):
    """Return a human-readable duration string."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m"


class DoorState:
    """
    Central state object. Call `update(event)` for every event that comes
    off the queue. Read properties to get current state for context building.
    """

    def __init__(self):
        # Open/closed
        self._is_open = False
        self._state_since = time.monotonic()

        # Last open duration (seconds) — filled when door closes
        self.last_open_duration = None

        # Human contact tracking
        self._last_contact_time = None      # monotonic, or None if never
        self._last_event_kind = None

        # Proximity / ignored streak
        self._person_present = False
        self._person_arrived_time = None
        self._interacted_since_arrival = False
        self.ignored_streak = 0             # people who came and left without interaction

        # Session counters
        self.session_opens = 0
        self.session_touches = 0
        self.session_slams = 0

        # Grip sample history: list of peak_g floats, most recent last
        self._grip_samples = []
        self._grip_maxlen = 20

        # Last accelerometer note
        self.last_accel_note = ""

        # Last touch force
        self.last_touch_force = None

        # Last known knock pattern (list of int intervals or None)
        self.last_knock_pattern = None

    # ── State update ──────────────────────────────────────────────────────────

    def update(self, event):
        """Update internal state from a DoorEvent. Must be called for every event."""
        kind = event.kind
        self._last_event_kind = kind

        if event.accel_note:
            self.last_accel_note = event.accel_note
        if event.touch_force:
            self.last_touch_force = event.touch_force
        if event.peak_g > 0:
            self._record_grip(event.peak_g)

        if kind in (KNOCK_SOFT, KNOCK_LOUD, KNOCK_PATTERN,
                    OPEN_GENTLE, OPEN_FORCE, CLOSE_GENTLE, SLAM,
                    TOUCH_GENTLE, TOUCH_ROUGH, LEAN):
            self._touch_event()

        if kind == KNOCK_PATTERN:
            self.last_knock_pattern = event.knock_pattern

        if kind in (OPEN_GENTLE, OPEN_FORCE):
            self._is_open = True
            self._state_since = time.monotonic()
            self.session_opens += 1

        if kind in (CLOSE_GENTLE, SLAM):
            if self._is_open:
                self.last_open_duration = time.monotonic() - self._state_since
            self._is_open = False
            self._state_since = time.monotonic()
            if kind == SLAM:
                self.session_slams += 1

        if kind in (TOUCH_GENTLE, TOUCH_ROUGH, KNOCK_SOFT, KNOCK_LOUD,
                    KNOCK_PATTERN, LEAN):
            self.session_touches += 1

        if kind == PROXIMITY_APPROACH:
            self._person_present = True
            self._person_arrived_time = time.monotonic()
            self._interacted_since_arrival = False

        if kind == PROXIMITY_DEPART:
            self._person_present = False
            if not self._interacted_since_arrival:
                self.ignored_streak += 1
            else:
                self.ignored_streak = 0   # they engaged; streak broken
            self._person_arrived_time = None
            self._interacted_since_arrival = False

    def _touch_event(self):
        self._last_contact_time = time.monotonic()
        self._interacted_since_arrival = True

    def _record_grip(self, peak_g):
        self._grip_samples.append(round(peak_g, 3))
        if len(self._grip_samples) > self._grip_maxlen:
            self._grip_samples.pop(0)

    # ── Readable properties ───────────────────────────────────────────────────

    @property
    def is_open(self):
        return self._is_open

    @property
    def state_label(self):
        return "open" if self._is_open else "closed"

    @property
    def state_duration(self):
        return _fmt_duration(time.monotonic() - self._state_since)

    @property
    def last_contact_str(self):
        if self._last_contact_time is None:
            return "never"
        return _fmt_duration(time.monotonic() - self._last_contact_time)

    @property
    def last_open_duration_str(self):
        if self.last_open_duration is None:
            return "unknown"
        return _fmt_duration(self.last_open_duration)

    @property
    def last_event_kind(self):
        return self._last_event_kind or "none"

    @property
    def grip_summary(self):
        """Short string describing recent grip strengths."""
        if not self._grip_samples:
            return "no grip data"
        avg = sum(self._grip_samples) / len(self._grip_samples)
        hi = max(self._grip_samples)
        return f"avg {avg:.2f}g, peak {hi:.2f}g over {len(self._grip_samples)} samples"

    @property
    def known_knock_patterns(self):
        """Mirror of KnockRecogniser.known_patterns — set externally by main loop."""
        return self._known_patterns if hasattr(self, "_known_patterns") else []

    def set_known_patterns(self, patterns):
        self._known_patterns = patterns
