"""
LLM client — talks to the Anthropic Messages API over Wi-Fi.

Two modes:
  respond(event, state)     — triggered by a real door event; uses the full
                              context block and returns spoken text.
  prequeue(state)           — called on a timer; asks the door to form a
                              thought it will hold until the next event.
                              Returns a short string stored as queued_thought.
"""

import json
import wifi
import socketpool
import adafruit_requests
import ssl
from context import build_context_block


API_URL = "https://api.anthropic.com/v1/messages"
MODEL   = "claude-opus-4-6"
MAX_TOKENS_RESPOND  = 120   # spoken words; keep it brief
MAX_TOKENS_PREQUEUE = 60    # internal thought; even briefer


def _load_persona_prompt(persona_name):
    """Read the persona system prompt from flash."""
    path = f"/personas/{persona_name}.md"
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return f"You are a door with the {persona_name} persona."


def _headers(api_key):
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


class LLMClient:

    def __init__(self, settings):
        self._api_key  = settings["ANTHROPIC_API_KEY"]
        self._persona  = settings.get("PERSONA", "enthusiast")
        self._system   = _load_persona_prompt(self._persona)

        self._voice_id = settings.get(
            f"VOICE_ID_{self._persona.upper()}", ""
        )

        # Set up a persistent requests session (reuses the TCP socket where possible)
        pool = socketpool.SocketPool(wifi.radio)
        self._session = adafruit_requests.Session(pool, ssl.create_default_context())

    # ── Public interface ──────────────────────────────────────────────────────

    def respond(self, event, state, queued_thought=""):
        """
        Build a full context block from `state` + `event` and ask the door
        to speak. Returns the text string, or None on error.
        """
        ctx = build_context_block(state, event, queued_thought=queued_thought)
        user_message = ctx   # the context block IS the user turn
        return self._call(user_message, max_tokens=MAX_TOKENS_RESPOND)

    def prequeue(self, state):
        """
        Ask the door to form a background thought without any triggering event.
        Returns a short string (the thought), or "" on error.
        """
        ctx_lines = [
            f"STATE: {state.state_label}",
            f"DURATION: {state.state_duration}",
            f"LAST_CONTACT: {state.last_contact_str}",
            f"IGNORED_STREAK: {state.ignored_streak}",
            f"SESSION_OPENS: {state.session_opens}",
            f"SESSION_TOUCHES: {state.session_touches}",
        ]
        prequeue_prompt = (
            "Nothing is happening right now. "
            "Form a thought — one or two sentences — that you are holding, "
            "ready to use or discard when the next event arrives. "
            "Do not speak it aloud yet. Just think it.\n\n"
            + "\n".join(ctx_lines)
        )
        result = self._call(prequeue_prompt, max_tokens=MAX_TOKENS_PREQUEUE)
        return result or ""

    # ── Internal ──────────────────────────────────────────────────────────────

    def _call(self, user_content, max_tokens):
        payload = {
            "model": MODEL,
            "max_tokens": max_tokens,
            "system": self._system,
            "messages": [
                {"role": "user", "content": user_content}
            ],
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
