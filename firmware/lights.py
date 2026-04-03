"""
Visual mouth — NeoPixel strip and optional servo, synced to speech only.

Both outputs represent the door's mouth and nothing else:
  - Silent : LEDs off, servo closed
  - Speaking: KITT-style scanner on the strip, servo pulses open/closed

NeoPixel
--------
The Prop-Maker FeatherWing routes its NeoPixel header to pin D5.
Set PIN_NEOPIXEL and NEOPIXEL_COUNT in settings.toml to match your strip.

Persona colours
  enthusiast    — warm amber      (255, 140,   0)
  stoic         — cool slate blue  ( 40, 120, 160)
  catastrophist — deep violet      (140,  40, 200)

Servo mouth (optional)
----------------------
Leave SERVO_PIN blank to disable. When enabled, the servo opens and closes
at SERVO_RATE_HZ while the door speaks, and returns to closed when done.
Requires adafruit_motor in /lib on the device.

Settings
--------
PIN_NEOPIXEL     = "D5"
NEOPIXEL_COUNT   = 30
SERVO_PIN        = ""       # blank = disabled
SERVO_OPEN_DEG   = 30
SERVO_CLOSED_DEG = 0
SERVO_RATE_HZ    = 3
"""

import time
import math
import board
import neopixel


PERSONA_COLORS = {
    "enthusiast":    (255, 140,   0),   # warm amber
    "stoic":         ( 40, 120, 160),   # cool slate blue
    "catastrophist": (140,  40, 200),   # deep violet
    "narrator":      (210, 170,  30),   # old lamplight gold
}
DEFAULT_COLOR = (100, 100, 100)


def _scale(color, brightness):
    return tuple(int(c * max(0.0, min(1.0, brightness))) for c in color)


# ── LightController ───────────────────────────────────────────────────────────

class LightController:
    """
    NeoPixel mouth — KITT scanner while speaking, off while silent.

    Call update() every loop iteration (including inside the TTS playback loop).
    Call start_speaking() / stop_speaking() around TTS playback.
    """

    def __init__(self, settings):
        pin_name = settings.get("PIN_NEOPIXEL", "D5")
        n        = int(settings.get("NEOPIXEL_COUNT", 30))
        persona  = settings.get("PERSONA", "enthusiast")

        pin = getattr(board, pin_name)
        self._strip = neopixel.NeoPixel(
            pin, n, brightness=1.0, auto_write=False, pixel_order=neopixel.GRB
        )
        self._n        = n
        self._color    = PERSONA_COLORS.get(persona, DEFAULT_COLOR)
        self._speaking = False
        self._t0       = 0.0

    def set_persona(self, persona):
        self._color = PERSONA_COLORS.get(persona, DEFAULT_COLOR)

    def start_speaking(self):
        self._speaking = True
        self._t0       = time.monotonic()

    def stop_speaking(self):
        self._speaking = False
        self._strip.fill((0, 0, 0))
        self._strip.show()

    def update(self):
        """Advance one animation frame. Call every loop iteration."""
        if not self._speaking:
            return
        elapsed = time.monotonic() - self._t0
        self._animate_speaking(elapsed)
        self._strip.show()

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
                self._strip[i] = _scale(self._color, 0.9 * (1.0 - dist / tail))


# ── ServoMouth ────────────────────────────────────────────────────────────────

class ServoMouth:
    """
    Single servo that pulses open/closed while the door speaks.
    Disabled when SERVO_PIN is blank (the default).
    Requires adafruit_motor in /lib on the device.
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
        self._servo.angle = self._closed_deg

    def start_speaking(self):
        if self._servo is None:
            return
        self._speaking = True
        self._t0       = time.monotonic()

    def stop_speaking(self):
        if self._servo is None:
            return
        self._speaking = False
        self._servo.angle = self._closed_deg

    def update(self):
        """Call every loop iteration during playback."""
        if self._servo is None or not self._speaking:
            return
        phase = (( time.monotonic() - self._t0) * self._rate_hz) % 1.0
        self._servo.angle = self._open_deg if phase < 0.5 else self._closed_deg
