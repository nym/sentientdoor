"""
LLM client — talks to the Anthropic Messages API over Wi-Fi.

Two modes:
  respond(event, state)  — triggered by a real door event; returns spoken text.
  prequeue(state)        — called on a timer; returns a short held thought.
"""

import json
import wifi
import socketpool
import adafruit_requests
import ssl
import network
from context import build_context_block


API_URL             = "https://api.anthropic.com/v1/messages"
MODEL               = "claude-opus-4-6"
MAX_TOKENS_RESPOND  = 120
MAX_TOKENS_PREQUEUE = 60


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_persona_prompt(persona_name):
    """
    Read shared_rules.md then the persona file, joined with a separator.
    Both files must live in /personas/ on the CIRCUITPY drive.
    Missing shared_rules.md is logged but not fatal; missing persona file
    falls back to a minimal stub.
    """
    parts = []
    for path in ("/personas/shared_rules.md", f"/personas/{persona_name}.md"):
        try:
            with open(path, "r") as f:
                parts.append(f.read())
        except OSError:
            print(f"Warning: could not read {path}")

    if not parts:
        return f"You are a door. Your persona is {persona_name}."
    return "\n\n---\n\n".join(parts)


def _sanitize_for_tts(text):
    """
    Strip markdown formatting that TTS would speak literally.
    CircuitPython has no `re` module — simple character replacement only.
    """
    for ch in ("*", "_", "`", "#", ">"):
        text = text.replace(ch, "")
    # Collapse runs of spaces left by stripping
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()


def _headers(api_key):
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


# ── Client ────────────────────────────────────────────────────────────────────

class LLMClient:

    def __init__(self, settings, session=None):
        self._settings = settings

        api_key = settings.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is missing from settings.toml")
        self._api_key = api_key

        self._persona = settings.get("PERSONA", "enthusiast")
        self._system  = _load_persona_prompt(self._persona)

        if session is not None:
            self._session = session
        else:
            pool = socketpool.SocketPool(wifi.radio)
            self._session = adafruit_requests.Session(pool, ssl.create_default_context())

    # ── Public interface ──────────────────────────────────────────────────────

    def respond(self, event, state, queued_thought=""):
        ctx  = build_context_block(state, event, queued_thought=queued_thought)
        text = self._call(ctx, max_tokens=MAX_TOKENS_RESPOND)
        return _sanitize_for_tts(text) if text else None

    def prequeue(self, state):
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
            "ready to use or discard when the next event arrives. "
            "Do not speak it aloud yet. Just think it.\n\n"
            + "\n".join(ctx_lines)
        )
        result = self._call(prompt, max_tokens=MAX_TOKENS_PREQUEUE)
        return _sanitize_for_tts(result) if result else ""

    # ── Internal ──────────────────────────────────────────────────────────────

    def _call(self, user_content, max_tokens):
        if not network.ensure_connected(self._settings):
            print("LLM: no network")
            return None

        payload = {
            "model": MODEL,
            "max_tokens": max_tokens,
            "system": self._system,
            "messages": [{"role": "user", "content": user_content}],
        }
        try:
            resp = self._session.post(
                API_URL,
                headers=_headers(self._api_key),
                data=json.dumps(payload),
                timeout=20,
            )
            if resp.status_code != 200:
                print(f"LLM error {resp.status_code}: {resp.text[:120]}")
                return None
            body = resp.json()
            return body["content"][0]["text"].strip()
        except Exception as e:  # noqa: BLE001
            print(f"LLM call failed: {e}")
            return None
