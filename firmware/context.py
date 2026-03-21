"""
Builds the sensor context block that is prepended to every LLM prompt.

The format matches exactly what is documented in each persona's
"Sensor Context Format" section.
"""

import time


def _time_of_day():
    t = time.localtime()
    h = t.tm_hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"


def _day_of_week():
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return days[time.localtime().tm_wday]


def _knock_pattern_str(pattern):
    """Convert list of int intervals to a readable string like '3-1-2'."""
    if not pattern:
        return "none"
    # Bucket intervals into rough rhythmic groups: short (<200ms)=1, medium=2, long=3
    buckets = []
    for ms in pattern:
        if ms < 200:
            buckets.append("1")
        elif ms < 450:
            buckets.append("2")
        else:
            buckets.append("3")
    return "-".join(buckets) + f"  [{'-'.join(str(ms) for ms in pattern)}ms]"


def build_context_block(state, last_event, queued_thought=""):
    """
    Returns a multi-line string in the sensor context format.

    Parameters
    ----------
    state         : DoorState instance
    last_event    : DoorEvent that triggered this response
    queued_thought: str — the door's pre-formed thought, may be empty
    """

    knock_str = (
        _knock_pattern_str(last_event.knock_pattern)
        if last_event.knock_pattern else "none"
    )

    open_dur = (
        state.last_open_duration_str
        if last_event.kind in ("close_gentle", "slam")
        else "n/a"
    )

    lines = [
        "```",
        f"STATE: {state.state_label}",
        f"DURATION: {state.state_duration}",
        f"LAST_CONTACT: {state.last_contact_str}",
        f"IGNORED_STREAK: {state.ignored_streak}",
        f"LAST_EVENT: {last_event.kind}",
        f"TOUCH_FORCE: {last_event.touch_force or 'n/a'}",
        f"OPEN_DURATION: {open_dur}",
        f"KNOCK_PATTERN: {knock_str}",
        f"SESSION_OPENS: {state.session_opens}",
        f"SESSION_TOUCHES: {state.session_touches}",
        f"ACCELEROMETER_NOTE: {state.last_accel_note or 'none'}",
        f"TIME_OF_DAY: {_time_of_day()}",
        f"DAY_OF_WEEK: {_day_of_week()}",
        f"QUEUED_THOUGHT: {queued_thought or ''}",
        "```",
    ]

    return "\n".join(lines)
