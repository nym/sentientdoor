"""
Reflex phrase engine — immediate responses that play while the LLM call runs.

Each persona has a JSON file at /personas/{persona}_reflexes.json with entries
keyed by event kind. Each entry has:
  "standard"  — 10 phrases, picked at random on the first occurrence
  "repeated"  — 10 phrases, played sequentially (Warcraft-style) on repeats

Counts reset on every PROXIMITY_APPROACH / PROXIMITY_DEPART cycle, so
escalation is per-visit.
"""

import json
import random


def load(persona):
    """Load reflex phrases for the given persona from /personas/."""
    try:
        with open(f"/personas/{persona}_reflexes.json", "r") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f"Reflexes: could not load {persona}_reflexes.json: {e}")
        return {}


class ReflexEngine:
    """
    Picks reflex phrases with Warcraft-style escalation.

    First occurrence of an event kind within a session → random pick from
    `standard`.  2nd+ occurrence → sequential through `repeated` (clamped
    at the last entry once exhausted).

    Counts reset on reset() — call this on each PROXIMITY_APPROACH and
    PROXIMITY_DEPART so escalation restarts fresh for each visitor.
    """

    def __init__(self, reflexes):
        self._reflexes = reflexes   # dict loaded from JSON
        self._counts   = {}         # event_kind → occurrence count this session

    def reset(self):
        """Reset occurrence counts. Call on PROXIMITY_APPROACH and DEPART."""
        self._counts = {}

    def pick(self, event_kind):
        """
        Return a phrase string, or None if no reflex is defined for this event.
        Increments the internal counter for event_kind.
        """
        entry = self._reflexes.get(event_kind)
        if not entry:
            return None

        count = self._counts.get(event_kind, 0)
        self._counts[event_kind] = count + 1

        if count == 0:
            phrases = entry.get("standard", [])
            return random.choice(phrases) if phrases else None
        else:
            phrases = entry.get("repeated", [])
            if not phrases:
                return None
            idx = min(count - 1, len(phrases) - 1)
            return phrases[idx]
