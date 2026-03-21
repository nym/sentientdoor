"""
Stub out every CircuitPython hardware module so firmware code can be imported
and tested on a standard CPython + pytest installation.

This file is loaded automatically by pytest before any test module.
"""

import sys

# ── Protect stdlib modules that firmware files shadow ─────────────────────────
# firmware/code.py shadows Python's stdlib 'code' module (used by pdb/pytest).
# Import it under its real name before we add firmware/ to sys.path.
import code as _stdlib_code  # noqa: F401
sys.modules["code"] = _stdlib_code

# ── Stub CircuitPython hardware modules ───────────────────────────────────────
from unittest.mock import MagicMock

_HW_MODULES = [
    "board",
    "busio",
    "digitalio",
    "analogio",
    "audiobusio",
    "audiocore",
    "audiopwmio",
    "adafruit_lis3dh",
    "adafruit_requests",
    "adafruit_ntp",
    "wifi",
    "socketpool",
    "rtc",
    "ssl",
    "supervisor",
    "toml",
    "network",        # firmware/network.py — not under test here; stub for importers
    "adafruit_requests",
]

for _mod in _HW_MODULES:
    sys.modules.setdefault(_mod, MagicMock())

# ── Add firmware/ to path ─────────────────────────────────────────────────────
import pathlib
_firmware = str(pathlib.Path(__file__).parent.parent / "firmware")
if _firmware not in sys.path:
    sys.path.insert(0, _firmware)
