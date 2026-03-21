"""
Visual output — NeoPixel strip and optional servo mouth.

NeoPixel (RGB strip, Knight Rider style)
-----------------------------------------
The LightController is a non-blocking state machine. Call update() every main
loop iteration (including during TTS playback) to advance the animation.

Modes
  IDLE      : slow breathing pulse in persona colour
  SPEAKING  : KITT-style scanner — bright dot bounces back and forth with a
              fading tail, giving the impression the door is "talking"
  REACT     : one-shot event flash keyed to the event type, then back to IDLE

Persona colours
  enthusiast    — warm amber      (255, 140,   0)
  stoic         — cool slate blue  ( 40, 120, 160)
  catastrophist — deep violet      (140,  40, 200)

Servo mouth (optional)
-----------------------
If SERVO_PIN is set in settings.toml, a ServoMouth object will open/close a
single servo to simulate lip movement while the door speaks. It does NOT
attempt real-time lip sync — it pulses at a regular rate during playback.
Requires adafruit_motor in /lib on the device.

Settings
--------
PIN_NEOPIXEL   = "D5"     # NeoPixel data pin — D5 on Prop-Maker FeatherWing
NEOPIXEL_COUNT = 30       # number of pixels on your strip
SERVO_PIN      = ""       # leave blank to disable servo mouth
"""

import time
import math
import board
import neopixel
from events import (
    KNOCK_SOFT, KNOCK_LOUD, KNOCK_PATTERN,
    OPEN_GENTLE, OPEN_FORCE, CLOSE_GENTLE, SLAM,
    TOUCH_GENTLE, TOUCH_ROUGH, LEAN,
    PROXIMITY_APPROACH, PROXIMITY_DEPART,
)


# ── Persona colours ────────────────────────────────────────────────────────────

PERSONA_COLORS = {
    "enthusiast":    (255, 140,   0),   # warm amber
    "stoic":         ( 40, 120, 160),   # cool slate blue
    "catastrophist": (140,  40, 200),   # deep violet
}
DEFAULT_COLOR = (100, 100, 100)


# ── Modes ─────────────────────────────────────────────────────────────────────

MODE_IDLE     = "idle"
MODE_SPEAKING = "speaking"
MODE_REACT    = "react"


# ── Colour helpers ─────────────────────────────────────────────────────────────

def _scale(color, brightness):
    """Scale an RGB tuple by a 0.0–1.0 brightness factor."""
    return tuple(int(c * max(0.0, min(1.0, brightness))) for c in color)


# ── LightController ───────────────────────────────────────────────────────────

class LightController:
    """
    Non-blocking NeoPixel animation controller.

    Usage
    -----
        lights = LightController(settings)

        # In main loop:
        lights.update()

        # On an event:
        lights.react(event.kind)

        # Around TTS playback:
        lights.start_speaking()
        tts.play(...)
        lights.stop_speaking()
    """

    def __init__(self, settings):
        pin_name = settings.get("PIN_NEOPIXEL", "D5")
        n        = int(settings.get("NEOPIXEL_COUNT", 30))
        persona  = settings.get("PERSONA", "enthusiast")

        pin = getattr(board, pin_name)
        self._strip = neopixel.NeoPixel(
            pin, n, brightness=1.0, auto_write=False, pixel_order=neopixel.GRB
        )
        self._n     = n
        self._color = PERSONA_COLORS.get(persona, DEFAULT_COLOR)

        self._mode   = MODE_IDLE
        self._t0     = time.monotonic()
        self._react_draw     = None
        self._react_duration = 0.0

    def set_persona(self, persona):
        """Switch colour palette when the persona changes."""
        self._color = PERSONA_COLORS.get(persona, DEFAULT_COLOR)

    # ── Mode transitions ──────────────────────────────────────────────────────

    def start_speaking(self):
        self._mode = MODE_SPEAKING
        self._t0   = time.monotonic()

    def stop_speaking(self):
        self._mode = MODE_IDLE
        self._t0   = time.monotonic()

    def react(self, event_kind):
        """Trigger a one-shot event animation (returns immediately)."""
        draw, duration = _react_for(event_kind, self._color)
        if draw is not None:
            self._react_draw     = draw
            self._react_duration = duration
            self._mode = MODE_REACT
            self._t0   = time.monotonic()

    # ── Main loop call ────────────────────────────────────────────────────────

    def update(self):
        """Advance the animation one frame. Call every loop iteration."""
        now     = time.monotonic()
        elapsed = now - self._t0

        if self._mode == MODE_IDLE:
            self._animate_idle(elapsed)

        elif self._mode == MODE_SPEAKING:
            self._animate_speaking(elapsed)

        elif self._mode == MODE_REACT:
            t = elapsed / self._react_duration
            if t >= 1.0:
                self._strip.fill((0, 0, 0))
                self._mode = MODE_IDLE
                self._t0   = now
            else:
                self._react_draw(self._strip, self._n, self._color, t)

        self._strip.show()

    # ── Animations ────────────────────────────────────────────────────────────

    def _animate_idle(self, elapsed):
        # Slow sine breathing: 4 s period, 2–15 % brightness
        t = (elapsed % 4.0) / 4.0
        b = 0.02 + 0.13 * (0.5 + 0.5 * math.sin(2 * math.pi * t - math.pi / 2))
        self._strip.fill(_scale(self._color, b))

    def _animate_speaking(self, elapsed):
        # KITT scanner: bright dot bounces L↔R with a 5-pixel fading tail
        period = 1.2
        tail   = 5
        phase  = elapsed % period
        half   = period / 2
        if phase < half:
            pos = (phase / half) * (self._n - 1)
        else:
            pos = (1.0 - (phase - half) / half) * (self._n - 1)

        self._strip.fill((0, 0, 0))
        for i in range(self._n):
            dist = abs(i - pos)
            if dist <= tail:
                b = 0.9 * (1.0 - dist / tail)
                self._strip[i] = _scale(self._color, b)


# ── One-shot reaction library ─────────────────────────────────────────────────
#
# Each entry is a (draw_fn, duration_s) pair.
# draw_fn(strip, n, color, t) — t runs 0→1 over duration_s.

def _react_for(event_kind, color):  # noqa: C901
    """Return (draw, duration) for event_kind, or (None, 0) if no animation."""

    if event_kind == KNOCK_SOFT:
        def draw(strip, n, c, t):
            b = max(0.0, 1.0 - abs(t - 0.4) / 0.4) * 0.5
            strip.fill(_scale(c, b))
        return draw, 0.5

    if event_kind == KNOCK_LOUD:
        def draw(strip, n, c, t):
            b = max(0.0, 1.0 - abs(t - 0.2) / 0.2) * 0.9
            strip.fill(_scale(c, b))
        return draw, 0.6

    if event_kind == KNOCK_PATTERN:
        def draw(strip, n, c, t):
            centre = n // 2
            reach  = int(t * centre)
            strip.fill((0, 0, 0))
            for i in range(n):
                if abs(i - centre) <= reach:
                    strip[i] = _scale(c, 0.7 * (1.0 - t * 0.5))
        return draw, 0.8

    if event_kind == OPEN_GENTLE:
        warm = (255, 220, 160)
        def draw(strip, n, c, t):
            centre = n // 2
            reach  = int(t * (centre + 1))
            strip.fill((0, 0, 0))
            for i in range(n):
                if abs(i - centre) <= reach:
                    strip[i] = _scale(warm, 0.6 * (1.0 - t * 0.3))
        return draw, 1.0

    if event_kind == OPEN_FORCE:
        def draw(strip, n, c, t):
            if t < 0.3:
                b = 0.9 if int(t * 20) % 2 == 0 else 0.0
                strip.fill(_scale((255, 30, 0), b))
            else:
                strip.fill(_scale(c, 0.4 * (1.0 - (t - 0.3) / 0.7)))
        return draw, 1.0

    if event_kind == CLOSE_GENTLE:
        def draw(strip, n, c, t):
            centre = n // 2
            edge   = int((1.0 - t) * centre)
            strip.fill((0, 0, 0))
            for i in range(n):
                if abs(i - centre) <= edge:
                    strip[i] = _scale(c, 0.4 * (1.0 - t))
        return draw, 0.8

    if event_kind == SLAM:
        def draw(strip, n, c, t):
            strip.fill(_scale((255, 0, 0), max(0.0, 1.0 - t * 3)))
        return draw, 0.8

    if event_kind == TOUCH_GENTLE:
        def draw(strip, n, c, t):
            centre = n // 2
            strip.fill((0, 0, 0))
            for i in range(n):
                dist = abs(i - centre)
                b = max(0.0, 0.4 - dist * 0.04) * math.sin(math.pi * t)
                strip[i] = _scale(c, b)
        return draw, 1.0

    if event_kind == TOUCH_ROUGH:
        def draw(strip, n, c, t):
            strip.fill(_scale((255, 80, 0), 0.8 * (1.0 - t)))
        return draw, 0.7

    if event_kind == LEAN:
        def draw(strip, n, c, t):
            strip.fill(_scale(c, 0.3 + 0.3 * math.sin(math.pi * t * 3)))
        return draw, 2.0

    if event_kind == PROXIMITY_APPROACH:
        def draw(strip, n, c, t):
            strip.fill(_scale(c, t * 0.15))
        return draw, 1.0

    if event_kind == PROXIMITY_DEPART:
        def draw(strip, n, c, t):
            strip.fill(_scale(c, (1.0 - t) * 0.15))
        return draw, 1.0

    return None, 0.0


# ── Servo mouth (optional) ────────────────────────────────────────────────────

class ServoMouth:
    """
    Pulses a single servo open/closed to simulate lip movement during speech.
    Does NOT do real-time lip sync — it cycles at a fixed rate while speaking.

    Requires adafruit_motor in /lib on the device.

    Settings
    --------
    SERVO_PIN        = "A3"    # PWM-capable pin for the servo signal wire
    SERVO_OPEN_DEG   = 30      # degrees open while speaking
    SERVO_CLOSED_DEG = 0       # degrees closed (rest position)
    SERVO_RATE_HZ    = 3       # open/close cycles per second while speaking
    """

    def __init__(self, settings):
        pin_name = settings.get("SERVO_PIN", "")
        if not pin_name:
            self._servo = None
            return

        import pwmio
        import adafruit_motor.servo as _servo_lib

        pwm = pwmio.PWMOut(
            getattr(board, pin_name), duty_cycle=2**15, frequency=50
        )
        self._servo      = _servo_lib.Servo(pwm)
        self._open_deg   = float(settings.get("SERVO_OPEN_DEG",   30))
        self._closed_deg = float(settings.get("SERVO_CLOSED_DEG",  0))
        self._rate_hz    = float(settings.get("SERVO_RATE_HZ",     3))
        self._speaking   = False
        self._t0         = 0.0
        self.close()

    def start_speaking(self):
        if self._servo is None:
            return
        self._speaking = True
        self._t0       = time.monotonic()

    def stop_speaking(self):
        if self._servo is None:
            return
        self._speaking = False
        self.close()

    def close(self):
        if self._servo is not None:
            self._servo.angle = self._closed_deg

    def update(self):
        """Call every loop iteration during playback."""
        if self._servo is None or not self._speaking:
            return
        elapsed = time.monotonic() - self._t0
        phase   = (elapsed * self._rate_hz) % 1.0
        # Open for first half of each cycle, closed for second
        self._servo.angle = self._open_deg if phase < 0.5 else self._closed_deg
