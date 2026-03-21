"""
SentientDoor — main entry point (CircuitPython, Feather ESP32-S3)

Boot sequence
-------------
1. Connect to Wi-Fi
2. Initialise sensors, LLM client, TTS player
3. Enter the main loop:
   a. Poll sensors → classify events
   b. Feed knocks through the pattern recogniser
   c. Update door state machine
   d. On a significant event: build context, call LLM, speak response
   e. On the prequeue timer: silently update the door's held thought

The door is always listening. It speaks only when something happens.
"""

import time
import os
import wifi
import supervisor

from sensors import SensorManager
from knock   import KnockRecogniser
from state   import DoorState
from llm     import LLMClient
from tts     import TTSPlayer
from events  import (
    EventQueue, DoorEvent,
    KNOCK_SOFT, KNOCK_LOUD, KNOCK_PATTERN,
    OPEN_GENTLE, OPEN_FORCE, CLOSE_GENTLE, SLAM,
    TOUCH_GENTLE, TOUCH_ROUGH, LEAN,
    PROXIMITY_APPROACH, PROXIMITY_DEPART,
    PREQUEUE_TICK,
)


# ── Events that warrant a spoken response ────────────────────────────────────

SPEAKING_EVENTS = {
    KNOCK_SOFT, KNOCK_LOUD, KNOCK_PATTERN,
    OPEN_GENTLE, OPEN_FORCE, CLOSE_GENTLE, SLAM,
    TOUCH_GENTLE, TOUCH_ROUGH, LEAN,
    PROXIMITY_APPROACH,       # someone approaching — door may greet them
}

# Events that update state but the door stays quiet (depart is internal bookkeeping)
SILENT_EVENTS = {PROXIMITY_DEPART}


# ── Helpers ──────────────────────────────────────────────────────────────────

def connect_wifi(settings):
    ssid = settings.get("WIFI_SSID", "")
    password = settings.get("WIFI_PASSWORD", "")
    print(f"Connecting to {ssid!r}...")
    wifi.radio.connect(ssid, password)
    print(f"Connected — IP: {wifi.radio.ipv4_address}")


def load_settings():
    """Read settings.toml from the CIRCUITPY root."""
    settings = {}
    try:
        import toml  # available in CircuitPython 9+
        with open("/settings.toml", "r") as f:
            settings = toml.load(f)
    except ImportError:
        # Fallback: CircuitPython exposes settings.toml vars as os.getenv
        keys = [
            "WIFI_SSID", "WIFI_PASSWORD",
            "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY",
            "PERSONA",
            "VOICE_ID_ENTHUSIAST", "VOICE_ID_STOIC", "VOICE_ID_CATASTROPHIST",
            "PIN_REED_SWITCH", "PIN_PIR", "PIN_POWER_ENABLE",
            "SLAM_THRESHOLD_G", "KNOCK_THRESHOLD_G", "LEAN_THRESHOLD_G",
            "LEAN_DURATION_S", "KNOCK_WINDOW_MS",
            "KNOCK_PATTERN_MIN", "KNOCK_PATTERN_MAX",
            "PREQUEUE_INTERVAL_S",
        ]
        for k in keys:
            v = os.getenv(k)
            if v is not None:
                settings[k] = v
    return settings


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    settings = load_settings()

    connect_wifi(settings)

    sensors   = SensorManager(settings)
    knock_rec = KnockRecogniser(settings)
    state     = DoorState()
    queue     = EventQueue(maxlen=16)
    llm       = LLMClient(settings)
    tts       = TTSPlayer(settings)

    queued_thought    = ""
    prequeue_interval = float(settings.get("PREQUEUE_INTERVAL_S", 300))
    last_prequeue     = time.monotonic()
    knock_flush_every = float(settings.get("KNOCK_WINDOW_MS", 800)) / 1000.0
    last_knock_flush  = time.monotonic()

    print("SentientDoor is awake.")

    while True:
        now = time.monotonic()

        # ── 1. Poll hardware sensors ─────────────────────────────────────────
        raw_event = sensors.poll()
        if raw_event is not None:
            # Feed knocks through the pattern recogniser first
            if raw_event.kind in (KNOCK_SOFT, KNOCK_LOUD):
                pattern_event = knock_rec.feed(raw_event)
                if pattern_event:
                    # A complete pattern was just confirmed — use it instead
                    queue.put(pattern_event)
                else:
                    queue.put(raw_event)
            else:
                queue.put(raw_event)

        # ── 2. Flush knock buffer on silence ─────────────────────────────────
        if now - last_knock_flush >= knock_flush_every:
            last_knock_flush = now
            pattern_event = knock_rec.flush()
            if pattern_event:
                queue.put(pattern_event)
            # Keep known patterns mirrored into state for context building
            state.set_known_patterns(knock_rec.known_patterns)

        # ── 3. Prequeue timer ─────────────────────────────────────────────────
        if now - last_prequeue >= prequeue_interval:
            last_prequeue = now
            print("Prequeue: updating door's held thought...")
            queued_thought = llm.prequeue(state) or ""
            print(f"Queued thought: {queued_thought!r}")

        # ── 4. Consume one event from the queue ───────────────────────────────
        event = queue.get()
        if event is None:
            continue

        # Always update state, even for silent events
        state.update(event)

        if event.kind in SILENT_EVENTS:
            continue

        if event.kind not in SPEAKING_EVENTS:
            continue

        # ── 5. Build context + call LLM ───────────────────────────────────────
        print(f"Event: {event}")
        text = llm.respond(event, state, queued_thought=queued_thought)
        queued_thought = ""   # consumed

        if not text:
            print("LLM returned nothing.")
            continue

        print(f"Door says: {text!r}")

        # ── 6. Speak ──────────────────────────────────────────────────────────
        tts.speak(text)


# ── Entry ─────────────────────────────────────────────────────────────────────
try:
    main()
except Exception as e:
    print(f"Fatal error: {e}")
    time.sleep(5)
    supervisor.reload()   # auto-restart on crash
