#!/usr/bin/env python3
"""
SentientDoor — desktop text adventure simulator

A Hitchhiker's Guide to the Galaxy-style interface for interacting with the
door virtually, without any hardware. Uses the Anthropic Python SDK directly
(streaming) and imports the firmware's pure-Python state/context modules.

Usage
-----
    python simulator.py
    python simulator.py --persona bouncer
    python simulator.py --api-key sk-ant-...

The ANTHROPIC_API_KEY environment variable is used if --api-key is not given.
"""

import sys
import os
import pathlib
import time
import json
import random
import argparse
import textwrap
import subprocess

# ── Add firmware/ to path so we can import state/context/events/knock ─────────
_here = pathlib.Path(__file__).parent
_firmware = str(_here / "firmware")
if _firmware not in sys.path:
    sys.path.insert(0, _firmware)

# ── Firmware pure-Python imports (no hardware required) ───────────────────────
from events import (
    DoorEvent,
    KNOCK_SOFT, KNOCK_LOUD, KNOCK_PATTERN,
    OPEN_GENTLE, OPEN_FORCE, CLOSE_GENTLE, SLAM,
    TOUCH_GENTLE, TOUCH_ROUGH, LEAN,
    PROXIMITY_APPROACH, PROXIMITY_DEPART,
    FORCE_GENTLE, FORCE_NORMAL, FORCE_ROUGH,
)
from state import DoorState
from context import build_context_block
from knock import KnockRecogniser

import anthropic
from reflexes import ReflexEngine


# ── ANSI colour helpers ───────────────────────────────────────────────────────

def _c(code, text):
    return f"\033[{code}m{text}\033[0m"

def gold(t):    return _c("33", t)
def cyan(t):    return _c("36", t)
def green(t):   return _c("32", t)
def dim(t):     return _c("2", t)
def bold(t):    return _c("1", t)
def italic(t):  return _c("3", t)


# ── Reflex loading ────────────────────────────────────────────────────────────

def load_reflexes(persona):
    """Load reflex JSON for the given persona from the local personas/ directory."""
    path = _here / "personas" / f"{persona}_reflexes.json"
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# ── Persona loading ───────────────────────────────────────────────────────────

PERSONAS = ("unreliable_narrator", "bouncer", "ken")

def load_persona(name):
    """Read shared_rules.md + persona file, joined with ---."""
    parts = []
    for path in (
        _here / "personas" / "shared_rules.md",
        _here / "personas" / f"{name}.md",
    ):
        try:
            parts.append(path.read_text())
        except FileNotFoundError:
            pass
    if not parts:
        return f"You are a door. Your persona is {name}."
    return "\n\n---\n\n".join(parts)


# ── LLM helpers ───────────────────────────────────────────────────────────────

MODEL            = "claude-opus-4-6"
MAX_TOKENS_SPEAK = 120
MAX_TOKENS_WAIT  = 60
LOG_WINDOW_S     = 3600   # keep last hour of interactions


def stream_response(client, system, messages, max_tokens):
    """Stream the LLM response, printing with a typewriter effect. Returns full text."""
    print(green("  ❝ "), end="", flush=True)
    full = []
    with client.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    ) as stream:
        for chunk in stream.text_stream:
            print(green(chunk), end="", flush=True)
            full.append(chunk)
    print()
    return "".join(full)


def build_messages(log, current_prompt):
    """
    Prepend the last hour of (user, assistant) log pairs before the current prompt.
    """
    cutoff = time.monotonic() - LOG_WINDOW_S
    messages = []
    for entry in log:
        if entry["t"] >= cutoff:
            messages.append({"role": "user",      "content": entry["user"]})
            messages.append({"role": "assistant",  "content": entry["assistant"]})
    messages.append({"role": "user", "content": current_prompt})
    return messages


# ── Command parser ────────────────────────────────────────────────────────────

HELP_TEXT = """
Commands (case-insensitive, DOOR suffix optional):
  TAP                  — soft single knock
  KNOCK                — firm knock
  BANG                 — loud, impolite knock
  KNOCK N TIMES        — pattern knock (N = 5–8; e.g. KNOCK 6 TIMES)
  OPEN                 — open the door gently
  FORCE OPEN           — wrench the door open
  CLOSE                — close the door gently
  SLAM                 — slam the door shut
  TOUCH                — place your hand on the door
  SHOVE / PUSH         — push the door hard
  LEAN                 — lean against the door (sustained)
  APPROACH             — walk up to the door
  LEAVE / DEPART       — walk away from the door
  WAIT                 — stand still; the door may form a thought
  LOOK / EXAMINE       — inspect the door's current state
    PERSONA <name>       — switch to unreliable_narrator / bouncer / ken
  HELP                 — show this list
  QUIT / EXIT          — leave the simulation
"""


def _strip(words, *remove):
    """Remove specific words from a word list."""
    return [w for w in words if w not in remove]


def parse_command(raw):
    """
    Returns (action, extra) where action is one of the internal command names
    or None if unrecognised.
    """
    words = raw.strip().lower().split()
    if not words:
        return None, None

    w = _strip(words, "the", "door", "on", "against", "at")
    cmd = w[0] if w else ""

    if cmd in ("quit", "exit", "q"):
        return "quit", None

    if cmd == "help":
        return "help", None

    if cmd == "look" or cmd == "examine":
        return "look", None

    if cmd == "wait":
        return "wait", None

    if cmd == "approach" or (cmd == "walk" and "up" in w):
        return "approach", None

    if cmd in ("leave", "depart") or (cmd == "walk" and "away" in w):
        return "leave", None

    if cmd == "tap":
        return "tap", None

    if cmd == "knock":
        # KNOCK N TIMES → pattern
        if len(w) >= 2:
            try:
                n = int(w[1])
                return "knock_pattern", n
            except ValueError:
                pass
        return "knock", None

    if cmd == "bang":
        return "bang", None

    if cmd in ("open",):
        return "open", None

    if cmd == "force" or (cmd == "yank"):
        return "force_open", None

    if cmd == "close":
        return "close", None

    if cmd == "slam":
        return "slam", None

    if cmd == "touch":
        return "touch", None

    if cmd in ("shove", "push"):
        return "shove", None

    if cmd == "lean":
        return "lean", None

    if cmd == "persona":
        name = w[1] if len(w) > 1 else ""
        return "persona", name

    return None, None


# ── Interaction descriptions ──────────────────────────────────────────────────

NARRATIONS = {
    "tap": (
        "You extend one finger and tap the door lightly, as if testing whether it is "
        "made of what it appears to be made of. It is."
    ),
    "knock": (
        "You knock on the door with the moderate enthusiasm of someone who expects "
        "an answer and is reasonably confident they will get one."
    ),
    "bang": (
        "You bang on the door with the kind of force that implies you are running late, "
        "or that the laws of property don't entirely apply to you."
    ),
    "open": (
        "You grasp the handle and push the door open in a completely ordinary way. "
        "The door swings on its hinges, which is exactly what doors are for."
    ),
    "force_open": (
        "You force the door open with considerably more urgency than the situation "
        "probably requires. The hinges note this."
    ),
    "close": (
        "You pull the door closed behind you. It fits its frame with a small, "
        "definitive sound."
    ),
    "slam": (
        "You slam the door. The sound travels some distance. "
        "Somewhere, a picture frame adjusts itself by a fraction of a millimetre."
    ),
    "touch": (
        "You place your hand flat against the door's surface. "
        "It is the temperature of things that have been standing in rooms for a long time."
    ),
    "shove": (
        "You push against the door with your shoulder. It does not open, because "
        "you have either just closed it or it was already closed. You knew that."
    ),
    "lean": (
        "You lean against the door. The door accepts your weight with the patience "
        "of something that has been doing exactly this for years. Time passes."
    ),
    "approach": (
        "You approach the door. It is, as it turns out, a door."
    ),
    "leave": (
        "You back away from the door. The door watches you go, "
        "in the sense that it faces the direction you are moving in."
    ),
    "wait": (
        "You wait. The universe continues to expand at a rate that is, on this scale, "
        "entirely imperceptible."
    ),
}


def make_knock_pattern_event(n):
    """
    Build a KNOCK_PATTERN DoorEvent with n notes and plausible fake intervals.
    Avoids KnockRecogniser entirely — we just fabricate intervals directly.
    """
    n = max(5, min(8, n))
    # Realistic-ish intervals: alternate short and medium gaps
    intervals = []
    for i in range(n - 1):
        intervals.append(200 if i % 2 == 0 else 350)
    interval_str = "-".join(str(ms) for ms in intervals)
    return DoorEvent(
        KNOCK_PATTERN,
        accel_note=f"{n}-note: {interval_str}",
        knock_pattern=intervals,
    )


# ── State display ─────────────────────────────────────────────────────────────

def print_state(state):
    label   = "OPEN" if state.is_open else "CLOSED"
    dur     = state.state_duration
    contact = state.last_contact_str
    ignored = state.ignored_streak
    opens   = state.session_opens
    touches = state.session_touches
    slams   = state.session_slams

    parts = [
        bold(label),
        dim(f"for {dur}"),
        dim(f"last touch {contact} ago") if contact != "never" else dim("never touched"),
        dim(f"ignored {ignored}") if ignored else None,
        dim(f"{opens} opens  {touches} touches  {slams} slams"),
    ]
    line = "  " + "  ·  ".join(p for p in parts if p)
    print(dim("─" * 60))
    print(line)
    print()


def print_look(state):
    """LOOK command — describe door state in HHGTTG flavour."""
    label = "open" if state.is_open else "closed"
    dur   = state.state_duration
    contact = state.last_contact_str

    desc = (
        f"The door is {bold(label)}, and has been for {bold(dur)}. "
    )
    if contact != "never":
        desc += f"It was last touched {bold(contact)} ago. "
    else:
        desc += "It has not been touched since the beginning of this session. "

    if state.ignored_streak:
        desc += (
            f"A total of {bold(str(state.ignored_streak))} "
            f"{'person has' if state.ignored_streak == 1 else 'people have'} "
            f"walked past without interacting. "
        )
    if state.session_opens or state.session_touches or state.session_slams:
        desc += (
            f"This session: {state.session_opens} opens, "
            f"{state.session_touches} touches, "
            f"{state.session_slams} slams."
        )

    for line in textwrap.wrap(desc, 72):
        print(gold("  " + line))
    print()


# ── Main simulator ────────────────────────────────────────────────────────────

def _play_sound(path, volume=0.8):
    """
    Play an audio file in the background (macOS afplay).
    Silently does nothing if the file is missing or afplay is unavailable.
    """
    if not pathlib.Path(path).exists():
        return
    try:
        subprocess.Popen(
            ["afplay", "-v", str(volume), str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass  # not macOS, or afplay not on PATH


STARTUP_SOUND = _here / "assets" / "startup.wav"

BANNER = r"""
  ╔══════════════════════════════════════════════════════════╗
  ║   TEXT ADVENTURE USING TEXT FOR SENTIENT DOOR            ║
  ║   DEMO 1.0                                               ║
  ║                                                          ║
  ║   "It is a well-known fact that those people who most    ║
  ║    want to rule people are, ipso facto, those least      ║
  ║    suited to do it."  — D. Adams                         ║
  ║                                                          ║
  ║   (The same principle may apply to doors.)               ║
  ╚══════════════════════════════════════════════════════════╝
"""


def run(api_key, initial_persona):
    client        = anthropic.Anthropic(api_key=api_key)
    persona       = initial_persona
    system        = load_persona(persona)
    state         = DoorState()
    queued_thought = ""
    log           = []   # list of {"t": monotonic, "user": str, "assistant": str}
    reflex_engine = ReflexEngine(load_reflexes(persona))

    _play_sound(STARTUP_SOUND)
    print(cyan(BANNER))
    print(gold(f"  Persona: {bold(persona.upper())}"))
    print(gold("  Type HELP for a list of commands.\n"))

    while True:
        # ── Prompt ────────────────────────────────────────────────────────────
        try:
            raw = input(dim("  > ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue

        action, extra = parse_command(raw)

        # ── Unrecognised ──────────────────────────────────────────────────────
        if action is None:
            print(gold(
                "  The Guide has no entry for that. "
                "Perhaps you mean something else? (HELP for commands)\n"
            ))
            continue

        # ── Meta commands ─────────────────────────────────────────────────────
        if action == "quit":
            print(gold(
                "\n  You leave. The door does not say goodbye, "
                "though it is clearly thinking something.\n"
            ))
            break

        if action == "help":
            print(cyan(HELP_TEXT))
            continue

        if action == "look":
            print_look(state)
            continue

        if action == "persona":
            name = (extra or "").strip()
            if name not in PERSONAS:
                print(gold(
                    f"  Unknown persona. Choose from: "
                    f"{', '.join(PERSONAS)}\n"
                ))
                continue
            persona       = name
            system        = load_persona(persona)
            state         = DoorState()
            queued_thought = ""
            log           = []   # fresh log for new persona
            reflex_engine = ReflexEngine(load_reflexes(persona))
            print(gold(
                f"\n  The door shimmers. Something about its fundamental attitude "
                f"has changed. It is now: {bold(persona.upper())}.\n"
            ))
            continue

        # ── Event commands ────────────────────────────────────────────────────
        # Narrate the action
        narration = NARRATIONS.get(action, "You interact with the door.")
        print()
        for line in textwrap.wrap(narration, 72):
            print(gold("  " + line))
        print()

        # Build a DoorEvent for the action
        event = _make_event(action, extra)
        if event is None:
            continue   # shouldn't happen

        # Update state
        state.update(event)

        # WAIT → prequeue-style thought, not a full response
        # (uses history for coherence but doesn't add itself to the log —
        #  it was never spoken aloud; it becomes QUEUED_THOUGHT next turn)
        if action == "wait":
            ctx_lines = [
                f"STATE: {state.state_label}",
                f"DURATION: {state.state_duration}",
                f"LAST_CONTACT: {state.last_contact_str}",
                f"IGNORED_STREAK: {state.ignored_streak}",
                f"SESSION_OPENS: {state.session_opens}",
                f"SESSION_TOUCHES: {state.session_touches}",
            ]
            prompt = (
                "Nothing is happening right now. "
                "Form a thought — one or two sentences — that you are holding, "
                "ready to use or discard when the next event arrives.\n\n"
                + "\n".join(ctx_lines)
            )
            queued_thought = stream_response(
                client, system, [{"role": "user", "content": prompt}], MAX_TOKENS_WAIT
            )
            print_state(state)
            continue

        # APPROACH → silent prepare call; store as queued_thought
        if event.kind == PROXIMITY_APPROACH:
            reflex_engine.reset()
            print(dim("  [preparing...]"))
            ctx_lines = [
                f"STATE: {state.state_label}",
                f"DURATION: {state.state_duration}",
                f"LAST_CONTACT: {state.last_contact_str}",
                f"IGNORED_STREAK: {state.ignored_streak}",
                f"SESSION_OPENS: {state.session_opens}",
                f"SESSION_TOUCHES: {state.session_touches}",
            ]
            prepare_prompt = (
                "Someone is approaching. You sense their presence before they interact. "
                "Based on your state and recent history, form a single thought about how "
                "you are preparing for this encounter. Do not speak it yet. Just hold it.\n\n"
                + "\n".join(ctx_lines)
            )
            messages = build_messages(log, prepare_prompt)
            resp = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS_WAIT,
                system=system,
                messages=messages,
            )
            queued_thought = resp.content[0].text.strip() if resp.content else ""
            print(dim(f"  [held: {queued_thought!r}]"))
            print_state(state)
            continue

        # DEPART → reset reflex session, no LLM call
        if event.kind == PROXIMITY_DEPART:
            reflex_engine.reset()
            print_state(state)
            continue

        # All other events → reflex phrase then full LLM response
        reflex = reflex_engine.pick(event.kind)
        if reflex:
            print(cyan(f"  {reflex}"))

        context_block = build_context_block(
            state, event, queued_thought=queued_thought
        )
        queued_thought = ""  # consumed

        messages = build_messages(log, context_block)
        reply = stream_response(client, system, messages, MAX_TOKENS_SPEAK)
        log.append({"t": time.monotonic(), "user": context_block, "assistant": reply})
        print_state(state)


def _make_event(action, extra):
    """Map an action name to a DoorEvent."""
    if action == "tap":
        return DoorEvent(KNOCK_SOFT, touch_force=FORCE_GENTLE,
                         peak_g=0.4, accel_note="light tap")

    if action == "knock":
        return DoorEvent(KNOCK_LOUD, touch_force=FORCE_NORMAL,
                         peak_g=1.0, accel_note="firm knock")

    if action == "bang":
        return DoorEvent(KNOCK_LOUD, touch_force=FORCE_ROUGH,
                         peak_g=2.2, accel_note="heavy impact")

    if action == "knock_pattern":
        n = extra if isinstance(extra, int) else 5
        return make_knock_pattern_event(n)

    if action == "open":
        return DoorEvent(OPEN_GENTLE, touch_force=FORCE_GENTLE,
                         peak_g=0.3, accel_note="gentle open")

    if action == "force_open":
        return DoorEvent(OPEN_FORCE, touch_force=FORCE_ROUGH,
                         peak_g=2.8, accel_note="forced entry")

    if action == "close":
        return DoorEvent(CLOSE_GENTLE, touch_force=FORCE_GENTLE,
                         peak_g=0.4, accel_note="quiet close")

    if action == "slam":
        return DoorEvent(SLAM, touch_force=FORCE_ROUGH,
                         peak_g=4.1, accel_note="hard slam")

    if action == "touch":
        return DoorEvent(TOUCH_GENTLE, touch_force=FORCE_GENTLE,
                         peak_g=0.2, accel_note="light touch")

    if action == "shove":
        return DoorEvent(TOUCH_ROUGH, touch_force=FORCE_ROUGH,
                         peak_g=1.9, accel_note="forceful push")

    if action == "lean":
        return DoorEvent(LEAN, touch_force=FORCE_GENTLE,
                         peak_g=0.35, accel_note="sustained lean")

    if action == "approach":
        return DoorEvent(PROXIMITY_APPROACH)

    if action == "leave":
        return DoorEvent(PROXIMITY_DEPART)

    if action == "wait":
        # Synthetic no-op — only used for the wait prequeue path
        return DoorEvent(PROXIMITY_APPROACH)  # won't be dispatched to LLM

    return None


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SentientDoor — HHGTTG text adventure simulator"
    )
    parser.add_argument(
        "--persona",
        choices=PERSONAS,
        default="unreliable_narrator",
        help="Door persona to start with (default: unreliable_narrator)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)",
    )
    args = parser.parse_args()

    if not args.api_key:
        print(
            "Error: no API key. Set ANTHROPIC_API_KEY or use --api-key.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    run(args.api_key, args.persona)


if __name__ == "__main__":
    main()
