"""
Event types and the shared event queue.

All sensor code produces DoorEvent objects and puts them on the queue.
The main loop consumes them one at a time.
"""

import time


# ── Event type constants ──────────────────────────────────────────────────────

KNOCK_SOFT       = "knock_soft"
KNOCK_LOUD       = "knock_loud"
KNOCK_PATTERN    = "knock_pattern"    # a recognised 5-8 note sequence
OPEN_GENTLE      = "open_gentle"
OPEN_FORCE       = "open_force"
CLOSE_GENTLE     = "close_gentle"
SLAM             = "slam"
TOUCH_GENTLE     = "touch_gentle"
TOUCH_ROUGH      = "touch_rough"
LEAN             = "lean"
MAIL_FLAP        = "mail_flap"
PROXIMITY_APPROACH = "proximity_approach"
PROXIMITY_DEPART   = "proximity_depart"


# ── Touch force classification ────────────────────────────────────────────────

FORCE_GENTLE = "gentle"
FORCE_NORMAL = "normal"
FORCE_ROUGH  = "rough"

def classify_force(magnitude_g):
    """Return a FORCE_* constant from peak accelerometer magnitude in g."""
    if magnitude_g < 0.6:
        return FORCE_GENTLE
    if magnitude_g < 1.8:
        return FORCE_NORMAL
    return FORCE_ROUGH


# ── DoorEvent ─────────────────────────────────────────────────────────────────

class DoorEvent:
    """
    A single thing that happened to the door.

    Attributes
    ----------
    kind          : one of the event-type constants above
    touch_force   : FORCE_* constant, or None if not a touch/knock
    peak_g        : peak accelerometer magnitude at event time (float)
    accel_note    : short human-readable summary of vibration ("firm grip, no slam")
    knock_pattern : list of inter-note intervals in ms, or None
    timestamp     : monotonic time of event (seconds)
    """

    def __init__(self, kind, touch_force=None, peak_g=0.0,
                 accel_note="", knock_pattern=None):
        self.kind = kind
        self.touch_force = touch_force
        self.peak_g = peak_g
        self.accel_note = accel_note
        self.knock_pattern = knock_pattern   # list of ints (ms gaps) or None
        self.timestamp = time.monotonic()

    def __repr__(self):
        return (
            f"DoorEvent({self.kind!r}, force={self.touch_force}, "
            f"peak={self.peak_g:.2f}g)"
        )


# ── Simple queue ──────────────────────────────────────────────────────────────

class EventQueue:
    """Tiny bounded FIFO. Drops oldest entry if full."""

    def __init__(self, maxlen=16):
        self._buf = []
        self._maxlen = maxlen

    def put(self, event):
        if len(self._buf) >= self._maxlen:
            self._buf.pop(0)   # drop oldest
        self._buf.append(event)

    def get(self):
        """Return the next event or None if empty."""
        if self._buf:
            return self._buf.pop(0)
        return None

    def __len__(self):
        return len(self._buf)
