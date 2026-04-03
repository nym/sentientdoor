"""
Sensor layer for the SentientDoor.

Hardware
--------
- LIS3DH accelerometer on the Adafruit Prop-Maker FeatherWing (I2C)
- Magnetic reed switch on PIN_REED_SWITCH (HIGH = door open, LOW = closed)
- PIR / proximity sensor on PIN_PIR (HIGH = person present)

Call `SensorManager.poll()` every loop tick. It classifies raw readings into
DoorEvent objects and puts them on the shared EventQueue.

Calibration
-----------
`SensorManager.__init__` calls `AccelDetector.calibrate()` automatically.
Keep the door still for the first second of boot — the calibration averages
50 readings to establish the gravity vector at rest, then subtracts it from
all future readings so that thresholds are relative to the resting state
rather than absolute magnitude (which always includes ~1 g from gravity).
"""

import time
import math
import board
import busio
import digitalio
from events import (
    DoorEvent,
    KNOCK_SOFT, KNOCK_LOUD, SLAM,
    LEAN,
    OPEN_GENTLE, OPEN_FORCE, CLOSE_GENTLE,
    PROXIMITY_APPROACH, PROXIMITY_DEPART,
    FORCE_GENTLE, FORCE_NORMAL, FORCE_ROUGH,
    classify_force,
)


# ── Accelerometer event detector ──────────────────────────────────────────────

class AccelDetector:
    """
    Wraps the LIS3DH and turns raw samples into vibration events.

    After calibrate() is called, readings have the resting gravity vector
    subtracted, so all thresholds are relative to the door's resting state.

    Knock / slam detection — peak-hold:
      - Sample at ~50 Hz
      - When calibrated magnitude exceeds knock_g, capture the peak
      - When magnitude falls back below knock_g * 0.6, emit the event

    Lean detection:
      - When horizontal deviation exceeds lean_g for lean_duration_s, emit LEAN
    """

    SAMPLE_INTERVAL  = 0.02   # 50 Hz
    CALIBRATION_N    = 50     # samples averaged at boot (~1 s)

    def __init__(self, slam_g, knock_g, lean_g, lean_duration_s):
        self.slam_g         = slam_g
        self.knock_g        = knock_g
        self.lean_g         = lean_g
        self.lean_duration_s = lean_duration_s

        try:
            import adafruit_lis3dh
            i2c = busio.I2C(board.SCL, board.SDA)
            self._lis = adafruit_lis3dh.LIS3DH_I2C(i2c)
            self._lis.range     = adafruit_lis3dh.RANGE_4_G
            self._lis.data_rate = adafruit_lis3dh.DATARATE_50_HZ
        except Exception as e:  # noqa: BLE001
            print(f"AccelDetector: no I2C device — running without accelerometer ({e})")
            self._lis = None

        self._last_sample = time.monotonic()
        self._in_event    = False
        self._peak_g      = 0.0

        self._lean_start  = None

        # Rolling window of resolved peak magnitudes (last 8) — for summary strings
        self._recent_peaks    = []
        self._last_peak_time  = None   # monotonic time of most recent resolved peak

        # Calibration offsets: resting gravity vector subtracted from every reading
        self._rest_x = 0.0
        self._rest_y = 0.0
        self._rest_z = 0.0

    # ── Calibration ───────────────────────────────────────────────────────────

    def calibrate(self):
        """
        Average CALIBRATION_N readings to find the resting gravity vector.
        Call once at boot while the door is stationary.
        Takes ~1 second.
        """
        if self._lis is None:
            print("AccelDetector: skipping calibration (no I2C device)")
            return

        xs, ys, zs = [], [], []
        for _ in range(self.CALIBRATION_N):
            x, y, z = self._lis.acceleration
            xs.append(x); ys.append(y); zs.append(z)
            time.sleep(self.SAMPLE_INTERVAL)

        G = 9.80665
        self._rest_x = sum(xs) / self.CALIBRATION_N / G
        self._rest_y = sum(ys) / self.CALIBRATION_N / G
        self._rest_z = sum(zs) / self.CALIBRATION_N / G
        print(
            f"Accel calibrated: rest=[{self._rest_x:.3f}, "
            f"{self._rest_y:.3f}, {self._rest_z:.3f}]g"
        )

    # ── Polling ───────────────────────────────────────────────────────────────

    def poll(self):
        """
        Call every loop tick. Returns a DoorEvent or None.
        """
        if self._lis is None:
            return None

        now = time.monotonic()
        if now - self._last_sample < self.SAMPLE_INTERVAL:
            return None
        self._last_sample = now

        x, y, z = self._lis.acceleration
        G = 9.80665
        # Subtract calibrated resting vector so mag ≈ 0 at rest
        xg = x / G - self._rest_x
        yg = y / G - self._rest_y
        zg = z / G - self._rest_z
        mag = math.sqrt(xg**2 + yg**2 + zg**2)

        if not self._in_event:
            if mag >= self.knock_g:
                self._in_event = True
                self._peak_g   = mag
            else:
                return self._check_lean(xg, yg, now)
        else:
            if mag > self._peak_g:
                self._peak_g = mag

            if mag < self.knock_g * 0.6:   # settled back down
                event = self._emit_vibration_event(now)
                self._in_event = False
                self._peak_g   = 0.0
                return event

        return None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _emit_vibration_event(self, now):
        peak = self._peak_g
        self._recent_peaks.append(peak)
        if len(self._recent_peaks) > 8:
            self._recent_peaks.pop(0)
        self._last_peak_time = now

        note  = self._accel_note(peak)
        force = classify_force(peak)

        if peak >= self.slam_g:
            return DoorEvent(SLAM, touch_force=FORCE_ROUGH, peak_g=peak, accel_note=note)

        kind = KNOCK_LOUD if peak >= self.knock_g * 1.8 else KNOCK_SOFT
        return DoorEvent(kind, touch_force=force, peak_g=peak, accel_note=note)

    def _check_lean(self, xg, yg, now):
        # Post-calibration: at rest xg≈0, yg≈0. Lean shifts gravity vector.
        horiz = math.sqrt(xg**2 + yg**2)
        if horiz >= self.lean_g:
            if self._lean_start is None:
                self._lean_start = now
            elif now - self._lean_start >= self.lean_duration_s:
                self._lean_start = None
                note = f"sustained lean ~{self.lean_duration_s:.0f}s, horiz={horiz:.2f}g"
                return DoorEvent(LEAN, accel_note=note, peak_g=horiz)
        else:
            self._lean_start = None
        return None

    def _accel_note(self, peak_g):
        if peak_g >= self.slam_g:
            return f"sharp impact {peak_g:.1f}g above rest — slam"
        if peak_g >= self.knock_g * 1.8:
            return f"firm knock {peak_g:.1f}g above rest"
        return f"soft knock {peak_g:.1f}g above rest"

    def recent_accel_summary(self):
        if self._lis is None:
            return "accelerometer not available"
        if not self._recent_peaks:
            return "no recent vibration"
        avg = sum(self._recent_peaks) / len(self._recent_peaks)
        hi  = max(self._recent_peaks)
        return (
            f"recent peaks avg={avg:.2f}g hi={hi:.2f}g "
            f"over {len(self._recent_peaks)} events (above rest)"
        )


# ── Reed switch (door open/closed) ────────────────────────────────────────────

_STALE_PEAK_WINDOW_S = 0.5   # ignore accel peak if older than this when door state changes

class ReedSwitch:
    """
    Magnetic reed switch, normally-closed.
    HIGH (pull-up, magnet gone) = door OPEN.
    LOW  (magnet present)       = door CLOSED.
    """

    def __init__(self, pin_name, accel_detector):
        pin = getattr(board, pin_name)
        self._io = digitalio.DigitalInOut(pin)
        self._io.direction = digitalio.Direction.INPUT
        self._io.pull      = digitalio.Pull.UP

        self._accel       = accel_detector
        self._open        = self._io.value
        self._state_since = time.monotonic()

    @property
    def is_open(self):
        return self._open

    @property
    def duration(self):
        return time.monotonic() - self._state_since

    def poll(self):
        """Returns a DoorEvent (OPEN_* or CLOSE_*) or None."""
        current = self._io.value
        if current == self._open:
            return None

        self._open        = current
        self._state_since = time.monotonic()

        # Only use the last accel peak if it happened recently
        now = time.monotonic()
        last_pt = self._accel._last_peak_time
        if last_pt is not None and (now - last_pt) <= _STALE_PEAK_WINDOW_S:
            peak  = self._accel._recent_peaks[-1] if self._accel._recent_peaks else 0.0
        else:
            peak  = 0.0

        note  = self._accel.recent_accel_summary()
        force = classify_force(peak)

        if self._open:
            kind = OPEN_FORCE if peak >= self._accel.knock_g else OPEN_GENTLE
        else:
            kind = SLAM if peak >= self._accel.slam_g else CLOSE_GENTLE

        return DoorEvent(kind, touch_force=force, peak_g=peak, accel_note=note)


# ── PIR / proximity sensor ────────────────────────────────────────────────────

class ProximitySensor:
    """
    PIR or equivalent digital presence sensor.
    HIGH = person within range.
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
        return DoorEvent(PROXIMITY_APPROACH if current else PROXIMITY_DEPART)


# ── SensorManager: wires everything together ──────────────────────────────────

_SLAM_DEDUP_WINDOW_S = 0.3   # suppress accel SLAM within this many seconds of a reed close

class SensorManager:
    """
    Single object the main loop calls.
    Returns one DoorEvent per call (or None).

    Slam deduplication: a physical slam causes the reed switch to emit a
    CLOSE/SLAM event and, slightly later, the accelerometer to also emit SLAM.
    We suppress the accel SLAM if it arrives within _SLAM_DEDUP_WINDOW_S of
    the reed closing, eliminating the double-speak.
    """

    def __init__(self, settings):
        self.accel = AccelDetector(
            slam_g=float(settings.get("SLAM_THRESHOLD_G", 3.0)),
            knock_g=float(settings.get("KNOCK_THRESHOLD_G", 0.5)),
            lean_g=float(settings.get("LEAN_THRESHOLD_G", 0.35)),
            lean_duration_s=float(settings.get("LEAN_DURATION_S", 4.0)),
        )
        print("Calibrating accelerometer — keep the door still...")
        self.accel.calibrate()

        self.reed      = ReedSwitch(settings.get("PIN_REED_SWITCH", "D6"), self.accel)
        self.proximity = ProximitySensor(settings.get("PIN_PIR", "D9"))

        self._last_close_time = 0.0   # monotonic time of last reed close event

    def poll(self):
        """
        Priority: reed switch state changes > accel events > proximity.
        Returns one DoorEvent or None.
        """
        now = time.monotonic()

        event = self.reed.poll()
        if event:
            if event.kind in (CLOSE_GENTLE, SLAM):
                self._last_close_time = now
            return event

        event = self.accel.poll()
        if event:
            # Suppress duplicate SLAM if reed already fired a close event recently
            if event.kind == SLAM and (now - self._last_close_time) < _SLAM_DEDUP_WINDOW_S:
                return None
            return event

        return self.proximity.poll()
