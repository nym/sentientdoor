"""
Sensor layer for the SentientDoor.

Hardware
--------
- LIS3DH accelerometer on the Adafruit Prop-Maker FeatherWing (I2C)
- Magnetic reed switch on PIN_REED_SWITCH (LOW = door closed)
- PIR / proximity sensor on PIN_PIR (HIGH = person present)

Call `SensorManager.poll()` every loop tick. It classifies raw readings into
DoorEvent objects and puts them on the shared EventQueue.
"""

import time
import math
import board
import busio
import digitalio
import adafruit_lis3dh
from events import (
    EventQueue, DoorEvent,
    KNOCK_SOFT, KNOCK_LOUD, SLAM,
    TOUCH_GENTLE, TOUCH_ROUGH, LEAN,
    OPEN_GENTLE, OPEN_FORCE, CLOSE_GENTLE,
    PROXIMITY_APPROACH, PROXIMITY_DEPART,
    FORCE_GENTLE, FORCE_NORMAL, FORCE_ROUGH,
    classify_force,
)


# ── Accelerometer event detector ──────────────────────────────────────────────

class AccelDetector:
    """
    Wraps the LIS3DH and turns raw samples into vibration events.

    Knock / slam detection uses a simple peak-hold approach:
      - Sample the magnitude at ~50 Hz
      - When magnitude exceeds KNOCK_THRESHOLD_G, capture the peak
      - After the peak falls back below threshold, emit the event
      - If the peak exceeds SLAM_THRESHOLD_G, emit SLAM instead

    Lean detection:
      - When the horizontal deviation from the door's resting axis exceeds
        LEAN_THRESHOLD_G for LEAN_DURATION_S, emit LEAN
    """

    SAMPLE_INTERVAL = 0.02   # 50 Hz

    def __init__(self, slam_g, knock_g, lean_g, lean_duration_s):
        self.slam_g = slam_g
        self.knock_g = knock_g
        self.lean_g = lean_g
        self.lean_duration_s = lean_duration_s

        i2c = busio.I2C(board.SCL, board.SDA)
        self._lis = adafruit_lis3dh.LIS3DH_I2C(i2c)
        self._lis.range = adafruit_lis3dh.RANGE_4_G
        self._lis.data_rate = adafruit_lis3dh.DATARATE_50_HZ

        self._last_sample = time.monotonic()
        self._in_event = False
        self._peak_g = 0.0
        self._samples_during_peak = []

        self._lean_start = None     # monotonic time lean began, or None

        # Rolling window for accel_note summary (last 8 peaks)
        self._recent_peaks = []

    def poll(self):
        """
        Call every loop tick. Returns a DoorEvent or None.
        Only one event is returned per call; caller should call repeatedly
        until None is returned to drain a burst.
        """
        now = time.monotonic()
        if now - self._last_sample < self.SAMPLE_INTERVAL:
            return None
        self._last_sample = now

        x, y, z = self._lis.acceleration          # m/s² from driver
        # Convert to g (1 g ≈ 9.80665 m/s²)
        xg = x / 9.80665
        yg = y / 9.80665
        zg = z / 9.80665
        mag = math.sqrt(xg**2 + yg**2 + zg**2)

        # ── Slam / knock peak detection ───────────────────────────────────
        if not self._in_event:
            if mag >= self.knock_g:
                self._in_event = True
                self._peak_g = mag
                self._samples_during_peak = [mag]
            else:
                # Check for lean while quiet
                return self._check_lean(xg, yg, zg, now)
        else:
            self._samples_during_peak.append(mag)
            if mag > self._peak_g:
                self._peak_g = mag

            if mag < self.knock_g * 0.6:   # settled back down
                event = self._emit_vibration_event()
                self._in_event = False
                self._peak_g = 0.0
                self._samples_during_peak = []
                return event

        return None

    def _emit_vibration_event(self):
        peak = self._peak_g
        self._recent_peaks.append(peak)
        if len(self._recent_peaks) > 8:
            self._recent_peaks.pop(0)

        note = self._accel_note(peak)
        force = classify_force(peak)

        if peak >= self.slam_g:
            return DoorEvent(SLAM, touch_force=FORCE_ROUGH, peak_g=peak, accel_note=note)

        kind = KNOCK_LOUD if peak >= self.knock_g * 1.8 else KNOCK_SOFT
        return DoorEvent(kind, touch_force=force, peak_g=peak, accel_note=note)

    def _check_lean(self, xg, yg, zg, now):
        # Horizontal deviation: sqrt(x²+y²) while z ≈ 1 g when upright
        horiz = math.sqrt(xg**2 + yg**2)
        if horiz >= self.lean_g:
            if self._lean_start is None:
                self._lean_start = now
            elif now - self._lean_start >= self.lean_duration_s:
                self._lean_start = None   # reset so we don't spam
                note = f"sustained lean ~{self.lean_duration_s:.0f}s, horiz={horiz:.2f}g"
                return DoorEvent(LEAN, accel_note=note, peak_g=horiz)
        else:
            self._lean_start = None
        return None

    def _accel_note(self, peak_g):
        if peak_g >= self.slam_g:
            return f"sharp impact {peak_g:.1f}g — slam"
        if peak_g >= self.knock_g * 1.8:
            return f"firm knock {peak_g:.1f}g"
        return f"soft knock {peak_g:.1f}g"

    def recent_accel_summary(self):
        """Short string summarising recent peaks — used in context block."""
        if not self._recent_peaks:
            return "no recent vibration"
        avg = sum(self._recent_peaks) / len(self._recent_peaks)
        hi = max(self._recent_peaks)
        return f"recent peaks avg={avg:.2f}g hi={hi:.2f}g over {len(self._recent_peaks)} events"


# ── Reed switch (door open/closed) ────────────────────────────────────────────

class ReedSwitch:
    """
    Magnetic reed switch.
    LOW (pulled low by closed magnet) = door CLOSED.
    HIGH (magnet gone) = door OPEN.
    """

    def __init__(self, pin_name, accel_detector):
        pin = getattr(board, pin_name)
        self._io = digitalio.DigitalInOut(pin)
        self._io.direction = digitalio.Direction.INPUT
        self._io.pull = digitalio.Pull.UP

        self._accel = accel_detector
        self._open = not self._io.value   # True = open
        self._state_since = time.monotonic()

    @property
    def is_open(self):
        return self._open

    @property
    def duration(self):
        return time.monotonic() - self._state_since

    def poll(self):
        """Returns a DoorEvent (OPEN_* or CLOSE_GENTLE) or None."""
        current = not self._io.value   # pulled-up, so LOW = closed → not LOW = open
        if current == self._open:
            return None

        # State changed
        prev_open = self._open
        self._open = current
        self._state_since = time.monotonic()

        # Use last accel peak to decide gentle vs force
        recent = self._accel._recent_peaks
        peak = recent[-1] if recent else 0.0
        note = self._accel.recent_accel_summary()
        force = classify_force(peak)

        if self._open:
            kind = OPEN_FORCE if peak >= 1.2 else OPEN_GENTLE
        else:
            kind = SLAM if peak >= self._accel.slam_g else CLOSE_GENTLE

        return DoorEvent(kind, touch_force=force, peak_g=peak, accel_note=note)


# ── PIR / proximity sensor ────────────────────────────────────────────────────

class ProximitySensor:
    """
    PIR or equivalent digital presence sensor.
    HIGH = person within range. Emits APPROACH on rising edge,
    DEPART on falling edge.
    """

    def __init__(self, pin_name):
        pin = getattr(board, pin_name)
        self._io = digitalio.DigitalInOut(pin)
        self._io.direction = digitalio.Direction.INPUT
        self._present = self._io.value

    @property
    def person_present(self):
        return self._present

    def poll(self):
        current = self._io.value
        if current == self._present:
            return None
        self._present = current
        kind = PROXIMITY_APPROACH if current else PROXIMITY_DEPART
        return DoorEvent(kind)


# ── SensorManager: wires everything together ──────────────────────────────────

class SensorManager:
    """
    Single object the main loop calls.
    Returns one DoorEvent per call (or None), draining the most urgent
    sensor first.
    """

    def __init__(self, settings):
        self.accel = AccelDetector(
            slam_g=float(settings.get("SLAM_THRESHOLD_G", 3.5)),
            knock_g=float(settings.get("KNOCK_THRESHOLD_G", 1.2)),
            lean_g=float(settings.get("LEAN_THRESHOLD_G", 0.35)),
            lean_duration_s=float(settings.get("LEAN_DURATION_S", 4.0)),
        )
        self.reed = ReedSwitch(
            settings.get("PIN_REED_SWITCH", "D6"),
            self.accel,
        )
        self.proximity = ProximitySensor(settings.get("PIN_PIR", "D9"))

    def poll(self):
        """
        Returns one DoorEvent or None. Call in a tight loop.
        Priority: reed switch state changes > accel events > proximity.
        """
        event = self.reed.poll()
        if event:
            return event

        event = self.accel.poll()
        if event:
            return event

        event = self.proximity.poll()
        return event
