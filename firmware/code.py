"""
SentientDoor — main entry point (CircuitPython, Feather ESP32-S3)

Boot sequence
-------------
1. Load settings from settings.toml via os.getenv
2. Connect to Wi-Fi
3. Create a single shared socket pool + requests session
4. Sync time via NTP (reuses the shared pool)
5. Calibrate the accelerometer (keep door still for ~1 s)
6. Initialise door state, knock recogniser, LLM client, TTS player
7. Enter the main loop:
   a. Poll sensors → classify events
   b. Feed knocks through the pattern recogniser
   c. Update door state machine
   d. On a significant event: build context, call LLM, speak
      (sensors are polled during playback so events are not lost)
   e. On the prequeue timer: silently update the door's held thought
      (suppressed if door has been idle > 30 minutes)
"""

import os
import time
import ssl
import socketpool
import wifi
import adafruit_requests
import supervisor

import network
from sensors import SensorManager
from knock   import KnockRecogniser
from state   import DoorState
from llm     import LLMClient
from tts     import TTSPlayer
from display import TFTDisplay
from lights   import LightController, ServoMouth
from reflexes import load as load_reflexes, ReflexEngine
from events  import (
    EventQueue,
    KNOCK_SOFT, KNOCK_LOUD, KNOCK_PATTERN,
    OPEN_GENTLE, OPEN_FORCE, CLOSE_GENTLE, SLAM,
    TOUCH_GENTLE, TOUCH_ROUGH, LEAN,
    PROXIMITY_APPROACH, PROXIMITY_DEPART,
)


SPEAKING_EVENTS = {
    KNOCK_SOFT, KNOCK_LOUD, KNOCK_PATTERN,
    OPEN_GENTLE, OPEN_FORCE, CLOSE_GENTLE, SLAM,
    TOUCH_GENTLE, TOUCH_ROUGH, LEAN,
}
SILENT_EVENTS = {PROXIMITY_APPROACH, PROXIMITY_DEPART}

PREQUEUE_IDLE_SUPPRESS_S = 1800   # suppress prequeue if idle > 30 minutes


def load_settings():
    keys = [
        "WIFI_SSID", "WIFI_PASSWORD",
        "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY",
        "PERSONA",
        "VOICE_ID_UNRELIABLE_NARRATOR", "VOICE_ID_BOUNCER", "VOICE_ID_KEN",
        "PIN_REED_SWITCH", "PIN_PIR", "PIN_POWER_ENABLE",
        "PIN_I2S_BCLK", "PIN_I2S_LRCLK", "PIN_I2S_DATA",
        "SLAM_THRESHOLD_G", "KNOCK_THRESHOLD_G", "LEAN_THRESHOLD_G",
        "LEAN_DURATION_S", "KNOCK_WINDOW_MS",
        "KNOCK_PATTERN_MIN", "KNOCK_PATTERN_MAX",
        "PREQUEUE_INTERVAL_S", "NTP_TZ_OFFSET",
        "PIN_NEOPIXEL", "NEOPIXEL_COUNT",
        "SERVO_PIN", "SERVO_OPEN_DEG", "SERVO_CLOSED_DEG", "SERVO_RATE_HZ",
        "TFT_CS", "TFT_DC", "TFT_RESET", "TFT_BACKLIGHT",
        "TFT_WIDTH", "TFT_HEIGHT", "TFT_ROTATION",
    ]
    settings = {}
    for k in keys:
        v = os.getenv(k)
        if v is not None:
            settings[k] = v
    return settings


def main():
    settings = load_settings()

    # ── Network ───────────────────────────────────────────────────────────────
    network.connect(settings)

    # One shared pool and session used by NTP, LLM, and TTS
    pool    = socketpool.SocketPool(wifi.radio)
    session = adafruit_requests.Session(pool, ssl.create_default_context())

    network.sync_ntp(settings, pool=pool)

    # ── Hardware + state ──────────────────────────────────────────────────────
    sensors   = SensorManager(settings)   # calibrates accel internally
    knock_rec = KnockRecogniser(settings)
    state     = DoorState()
    queue     = EventQueue(maxlen=16)
    llm       = LLMClient(settings, session=session)
    tts       = TTSPlayer(settings, session=session)
    lights        = LightController(settings)
    servo         = ServoMouth(settings)
    tft           = TFTDisplay(settings)
    door_reflexes = load_reflexes(settings.get("PERSONA", "unreliable_narrator"))
    reflex_engine = ReflexEngine(door_reflexes)

    queued_thought    = ""
    prequeue_interval = float(settings.get("PREQUEUE_INTERVAL_S", 300))
    last_prequeue     = time.monotonic()
    knock_flush_every = float(settings.get("KNOCK_WINDOW_MS", 800)) / 1000.0
    last_knock_flush  = time.monotonic()
    last_activity     = time.monotonic()

    print("SentientDoor is awake.")

    while True:
        now = time.monotonic()

        # ── 1. Poll sensors + update LEDs ────────────────────────────────────
        lights.update()
        raw_event = sensors.poll()
        if raw_event is not None:
            if raw_event.kind in (KNOCK_SOFT, KNOCK_LOUD):
                pattern_event = knock_rec.feed(raw_event)
                queue.put(pattern_event if pattern_event else raw_event)
            else:
                queue.put(raw_event)

        # ── 2. Flush knock buffer on silence ──────────────────────────────────
        if now - last_knock_flush >= knock_flush_every:
            last_knock_flush = now
            pattern_event = knock_rec.flush()
            if pattern_event:
                queue.put(pattern_event)
            state.set_known_patterns(knock_rec.known_patterns)

        # ── 3. Prequeue timer ─────────────────────────────────────────────────
        if now - last_prequeue >= prequeue_interval:
            last_prequeue = now
            idle_s = now - last_activity
            if idle_s < PREQUEUE_IDLE_SUPPRESS_S:
                print("Prequeue: updating held thought...")
                queued_thought = llm.prequeue(state) or ""
                print(f"Queued thought: {queued_thought!r}")
            else:
                print(f"Prequeue: suppressed (idle {idle_s / 60:.0f}m)")

        # ── 4. Consume one event ──────────────────────────────────────────────
        event = queue.get()
        if event is None:
            continue

        state.update(event)
        last_activity = now

        # ── PROXIMITY_APPROACH → silent prepare, reset reflex session ─────────
        if event.kind == PROXIMITY_APPROACH:
            reflex_engine.reset()
            print("Approach: preparing...")
            queued_thought = llm.prepare(state) or ""
            print(f"Prepared thought: {queued_thought!r}")
            continue

        # ── PROXIMITY_DEPART → reset reflex session ───────────────────────────
        if event.kind == PROXIMITY_DEPART:
            reflex_engine.reset()
            continue

        if event.kind not in SPEAKING_EVENTS:
            continue

        # ── 5. Reflex phrase (immediate, covers LLM latency) ──────────────────
        reflex = reflex_engine.pick(event.kind)
        if reflex:
            print(f"[reflex] {reflex}")

        # ── 6. LLM ───────────────────────────────────────────────────────────
        print(f"Event: {event}")
        text = llm.respond(event, state, queued_thought=queued_thought)
        queued_thought = ""

        if not text:
            print("LLM returned nothing.")
            continue

        print(f"Door says: {text!r}")

        # ── 7. Speak (sensors, LEDs, servo updated during playback) ──────────
        tts.speak(text, sensor_manager=sensors, event_queue=queue,
                  lights=lights, servo=servo, display=tft)


try:
    main()
except Exception as e:
    print(f"Fatal error: {e}")
    time.sleep(5)
    supervisor.reload()
