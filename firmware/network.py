"""
Wi-Fi connection management and NTP time sync.

All modules that need network access call `ensure_connected(settings)` before
making requests. It reconnects silently if the radio has dropped.
`sync_ntp` is called once at boot to set the RTC from network time.
"""

import time
import wifi
import rtc
import socketpool
import ssl


def connect(settings):
    """Connect to Wi-Fi. Raises on failure after max_retries."""
    ssid = settings.get("WIFI_SSID", "")
    password = settings.get("WIFI_PASSWORD", "")
    _connect_once(ssid, password, max_retries=5)
    print(f"Wi-Fi connected — {wifi.radio.ipv4_address}")


def ensure_connected(settings):
    """
    Reconnect if the radio has dropped. Call before any network request.
    Returns True if connected, False if all retries failed.
    """
    if wifi.radio.connected:
        return True
    print("Wi-Fi dropped — reconnecting...")
    ssid = settings.get("WIFI_SSID", "")
    password = settings.get("WIFI_PASSWORD", "")
    try:
        _connect_once(ssid, password, max_retries=3)
        return True
    except RuntimeError as e:
        print(f"Reconnect failed: {e}")
        return False


def sync_ntp(settings, pool=None):
    """
    Set the RTC from an NTP server. Call once after initial Wi-Fi connect.
    Pass the shared socket pool to avoid creating a second SocketPool instance.
    Requires adafruit_ntp in /lib on the device.
    """
    tz_offset = int(settings.get("NTP_TZ_OFFSET", 0))
    try:
        import adafruit_ntp
        if pool is None:
            pool = socketpool.SocketPool(wifi.radio)
        ntp = adafruit_ntp.NTP(pool, tz_offset=tz_offset, socket_timeout=10)
        rtc.RTC().datetime = ntp.datetime
        t = time.localtime()
        print(f"NTP sync OK — {t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d} "
              f"{t.tm_hour:02d}:{t.tm_min:02d} UTC{tz_offset:+d}")
    except Exception as e:  # noqa: BLE001
        # Non-fatal: time context will be wrong but door still works.
        print(f"NTP sync failed (time context will be inaccurate): {e}")


# ── Internal ──────────────────────────────────────────────────────────────────

def _connect_once(ssid, password, max_retries=3):
    for attempt in range(max_retries):
        try:
            wifi.radio.connect(ssid, password)
            return
        except Exception as e:  # noqa: BLE001
            print(f"Wi-Fi attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)   # back-off: 1s, 2s, 4s
    raise RuntimeError(f"Could not connect to {ssid!r} after {max_retries} attempts")
