"""
Hardware verification + live 9-DoF visualisation for SentientDoor.

Phase 1 — Hardware checks (runs automatically on boot):
  - I2C bus scan for ISM330DHCX (0x6A) and LIS3MDL (0x1C)
  - ISM330DHCX accelerometer + gyroscope sanity check
  - LIS3MDL magnetometer read test
  - DFRobot Speech Synthesis Mobile V2.2.0 (UART, 115200): says "hello cruel world"
  - I2S amp (MAX98357 on A0/A1/A2): plays 440 Hz tone, D0=proceed D1=retry

  Failures show BIG banners — impossible to miss on the serial console.

Phase 2 — Live 3D display (runs continuously after all tests pass):
  A wireframe cube and colour-coded XYZ axes rendered in ASCII,
  rotating in real time from the fused 9-DoF orientation.
  Accel + magnetometer → roll / pitch / yaw.
  All raw sensor values displayed below the wireframe.

Hardware:
  Feather ESP32-S3
  ISM330DHCX + LIS3MDL FeatherWing (I2C, via QWIIC or stacked)
  DFRobot Speech Synthesis Mobile V2.2.0 (UART, 9600 baud, TX/RX)

Required CircuitPython libraries in /lib:
  adafruit_lsm6ds/      (contains ISM330DHCX — install via: circup install adafruit-lsm6ds)
  adafruit_lis3mdl.mpy  (install via: circup install adafruit-lis3mdl)
  adafruit_register/
  adafruit_bus_device/

Copy to CIRCUITPY as code.py.  Monitor via serial console.
"""

import array
import time
import math
import board
import busio
import gc


# ── ANSI terminal codes ──────────────────────────────────────────────────────
_A        = "\x1b["
CLEAR     = _A + "2J"
HOME      = _A + "H"
HIDE_CUR  = _A + "?25l"
SHOW_CUR  = _A + "?25h"
CLEAR_EOL = _A + "K"
DIM       = _A + "2m"
BOLD      = _A + "1m"
RED       = _A + "1;31m"
GREEN     = _A + "1;32m"
YELLOW    = _A + "1;33m"
BLUE      = _A + "1;34m"
CYAN      = _A + "1;36m"
WHITE     = _A + "1;37m"
RST       = _A + "0m"


# ── 3D rendering constants ───────────────────────────────────────────────────
GW, GH   = 50, 20              # character grid: width × height
CX, CY   = GW // 2, GH // 2   # grid centre
SCALE    = 5                    # projection scale factor

# Unit cube: 8 vertices
_CUBE_V = [
    (-1, -1, -1), ( 1, -1, -1), ( 1,  1, -1), (-1,  1, -1),
    (-1, -1,  1), ( 1, -1,  1), ( 1,  1,  1), (-1,  1,  1),
]
# 12 edges (pairs of vertex indices)
_CUBE_E = [
    (0, 1), (1, 2), (2, 3), (3, 0),   # back face
    (4, 5), (5, 6), (6, 7), (7, 4),   # front face
    (0, 4), (1, 5), (2, 6), (3, 7),   # connecting edges
]
# Axis endpoints: (origin, tip) — extend past the cube so they're visible
_AXIS_TIPS  = [(1.8, 0, 0), (0, 1.8, 0), (0, 0, 1.8)]
_AXIS_CHARS = [ord('x'), ord('y'), ord('z')]
_AXIS_LABEL = [ord('X'), ord('Y'), ord('Z')]
# Char-to-colour map used at render time (keyed by byte value)
_CHAR_COL = {
    ord('.'): DIM,
    ord('x'): RED,   ord('X'): RED,
    ord('y'): GREEN, ord('Y'): GREEN,
    ord('z'): BLUE,  ord('Z'): BLUE,
    ord('O'): YELLOW,
}

# Pre-allocated blank row (copied into grid each frame)
_BLANK = b' ' * GW


# ═══════════════════════════════════════════════════════════════════════════════
#  Banner helpers — big, coloured, unmissable
# ═══════════════════════════════════════════════════════════════════════════════

def _banner(colour, tag, title, details=None):
    """Print a large bordered banner.  `details` may be a list of strings."""
    inner_w = max(len(title) + len(tag) + 5, 42)
    if details:
        for d in details:
            inner_w = max(inner_w, len(d) + 4)
    bar = "#" * (inner_w + 4)
    def _pad(text):
        return text + " " * (inner_w - len(text))
    tag_title = tag + ": " + title
    print()
    print(f"{colour}{bar}")
    print("#  " + _pad("") + "#")
    print("#  " + _pad(tag_title) + "#")
    print("#  " + _pad("") + "#")
    if details:
        for line in details:
            print("#  " + _pad(line) + "#")
        print("#  " + _pad("") + "#")
    print(bar + RST)
    print()


def banner_fail(title, *detail_lines):
    _banner(RED, "FAIL", title, detail_lines if detail_lines else None)


def banner_pass(title):
    _banner(GREEN, "OK", title)


_BIG_PASS = [
    " ####    ###    ####   ####  ",
    " #   #  #   #  #      #     ",
    " ####   #####   ###    ###   ",
    " #      #   #      #      # ",
    " #      #   #  ####   ####  ",
]
_BIG_FAIL = [
    " #####   ###   #####  #     ",
    " #      #   #    #    #     ",
    " ####   #####    #    #     ",
    " #      #   #    #    #     ",
    " #      #   #  #####  ##### ",
]


def banner_result(passed):
    art = _BIG_PASS if passed else _BIG_FAIL
    col = GREEN if passed else RED
    w = len(art[0]) + 6
    bar = "=" * w
    print()
    print(f"{col}{bar}")
    for line in art:
        print(f"   {line}")
    print(f"{bar}{RST}")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 1 — hardware tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_i2c(i2c):
    """Scan the shared I2C bus for both expected sensors."""
    print(f"{CYAN}--- I2C Bus Scan ---{RST}")
    while not i2c.try_lock():
        pass
    try:
        addrs = i2c.scan()
    finally:
        i2c.unlock()

    known = {
        0x6A: "ISM330DHCX",       0x6B: "ISM330DHCX (alt addr)",
        0x1C: "LIS3MDL",          0x1E: "LIS3MDL (alt addr)",
    }
    found_imu = False
    found_mag = False
    for a in addrs:
        tag = known.get(a, "unknown")
        print(f"  0x{a:02X}  {tag}")
        if a in (0x6A, 0x6B):
            found_imu = True
        if a in (0x1C, 0x1E):
            found_mag = True

    if not addrs:
        banner_fail("I2C BUS — NO DEVICES",
                     "Nothing found on the I2C bus.",
                     "Is the FeatherWing seated properly?",
                     "Check SCL/SDA connections.")
        return False
    if not found_imu:
        banner_fail("ISM330DHCX NOT FOUND",
                     "Expected at 0x6A or 0x6B.",
                     "Reseat the FeatherWing and reset.")
        return False
    if not found_mag:
        banner_fail("LIS3MDL NOT FOUND",
                     "Expected at 0x1C or 0x1E.",
                     "Reseat the FeatherWing and reset.")
        return False

    banner_pass("I2C — both sensors detected")
    return True


def test_imu(i2c):
    """Initialise and sanity-check the ISM330DHCX + LIS3MDL.

    Returns (imu_obj, mag_obj).  Either may be None on failure.
    """
    print(f"{CYAN}--- IMU Read Test ---{RST}")

    # -- ISM330DHCX (accel + gyro) --
    imu = None
    try:
        from adafruit_lsm6ds.ism330dhcx import ISM330DHCX
        imu = ISM330DHCX(i2c)
        print(f"  ISM330DHCX  init OK")
    except Exception as e:
        banner_fail("ISM330DHCX INIT", str(e))
        return None, None

    # -- LIS3MDL (magnetometer) --
    mag = None
    try:
        from adafruit_lis3mdl import LIS3MDL
        mag = LIS3MDL(i2c)
        print(f"  LIS3MDL     init OK")
    except Exception as e:
        banner_fail("LIS3MDL INIT", str(e))
        # Continue — accel+gyro still useful without mag

    # Accel sanity: average 5 samples, magnitude should be ~9.81 m/s^2
    total = 0.0
    for _ in range(5):
        ax, ay, az = imu.acceleration
        total += math.sqrt(ax * ax + ay * ay + az * az)
        time.sleep(0.05)
    avg = total / 5.0
    print(f"  Accel magnitude (avg 5): {avg:.2f} m/s^2")

    if not (7.0 < avg < 13.0):
        banner_fail("ACCEL SANITY CHECK",
                     f"Magnitude {avg:.2f} m/s^2 — expected ~9.81",
                     "Sensor may be damaged or board is moving.")
        return imu, mag   # return them anyway — caller decides

    # Quick gyro + mag read
    gx, gy, gz = imu.gyro
    print(f"  Gyro:  ({gx:+.2f}, {gy:+.2f}, {gz:+.2f}) dps")
    if mag:
        mx, my, mz = mag.magnetic
        print(f"  Mag:   ({mx:+.1f}, {my:+.1f}, {mz:+.1f}) uT")

    banner_pass(f"IMU — accel {avg:.1f} m/s^2, gyro OK" +
                (", mag OK" if mag else ", mag MISSING"))
    return imu, mag


def test_speech_synthesis():
    """Test DFRobot Speech Synthesis Mobile V2.2.0 over UART.

    Module switch must be set to UART.  Wiring: TX→RX, RX→TX, GND, 5 V.
    Baud rate: 115200 (from official DFRobot library).

    English packet format (per DFRobot_SpeechSynthesis.cpp):
      [0xFD] [len_H] [len_L] [0x01] [0x00] [text bytes]
      where len = 2 + len(text)  (covers cmd byte + encoding byte + text)
    Status bytes:
      0x41 = synthesis complete / starting playback
      0x4F = playback complete
    """
    BUSY = 0x41
    IDLE = 0x4F
    print(f"{CYAN}--- DFRobot Speech Synthesis Test (UART) ---{RST}")

    try:
        uart = busio.UART(board.TX, board.RX, baudrate=115200, timeout=0.05)
    except Exception as e:
        banner_fail("SPEECH SYNTHESIS UART INIT", str(e),
                     "Check TX/RX wiring and that no other code holds the UART.")
        return False

    def _speak(text):
        """Send one English synthesis packet."""
        data   = text if isinstance(text, (bytes, bytearray)) else text.encode()
        length = len(data) + 2              # +1 cmd (0x01) +1 encoding (0x00)
        header = bytes([0xFD, (length >> 8) & 0xFF, length & 0xFF, 0x01, 0x00])
        # flush stale rx bytes before sending
        while uart.in_waiting:
            uart.read(uart.in_waiting)
        uart.write(header + data)

    def _wait(timeout):
        """Poll for 0x41 then 0x4F within timeout seconds. Returns True if heard both."""
        deadline = time.monotonic() + timeout
        got_busy = False
        while time.monotonic() < deadline:
            b = uart.read(1)
            if not b:
                time.sleep(0.01)
                continue
            if b[0] == BUSY:
                got_busy = True
            elif b[0] == IDLE and got_busy:
                return True
        return False

    # Initialise module (mirrors DFRobot library begin())
    for cmd in (b"[v5]", b"[s5]", b"[m3]", b"[h2]"):
        _speak(cmd)
        _wait(3.0)

    # Speak the test phrase
    _speak(b"hello cruel world")
    print(f"  Sent: 'hello cruel world'  (waiting for 0x41 then 0x4F ...)")

    if not _wait(10.0):
        uart.deinit()
        banner_fail("SPEECH SYNTHESIS — NO RESPONSE",
                     "Sent packet but module never replied 0x41 + 0x4F.",
                     "Check 5 V supply, TX/RX swap, module switch = UART.")
        return False

    uart.deinit()
    banner_pass("Speech Synthesis — 'hello cruel world' spoken OK")
    return True


def test_i2s_audio():
    """Play a 440 Hz tone via I2S and wait for button confirmation.

    D0 = heard it / proceed    D1 = didn't hear it / try again
    Pins: A0 = BCLK, A1 = LRCLK, A2 = DATA  (settings.toml defaults).
    Buttons wired normally-open to GND (internal pull-up).
    """
    import audiobusio
    import audiocore
    import digitalio

    print(f"{CYAN}--- I2S Audio Test ---{RST}")
    print(f"  {GREEN}D0{RST} = heard it / proceed   {YELLOW}D1{RST} = try again")

    btn_ok    = digitalio.DigitalInOut(board.D0)
    btn_retry = digitalio.DigitalInOut(board.D1)
    btn_ok.switch_to_input(pull=digitalio.Pull.UP)
    btn_retry.switch_to_input(pull=digitalio.Pull.UP)

    N    = 256
    FREQ = 440
    sine = array.array("h", [int(32767 * math.sin(2 * math.pi * i / N)) for i in range(N)])

    try:
        i2s = audiobusio.I2SOut(board.A0, board.A1, board.A2)
    except Exception as e:
        btn_ok.deinit(); btn_retry.deinit()
        banner_fail("I2S INIT FAILED", str(e), "Check A0/A1/A2 wiring to MAX98357.")
        return False

    sample = audiocore.RawSample(sine, sample_rate=FREQ * N)

    while True:
        print(f"  Playing 440 Hz ...")
        try:
            i2s.play(sample, loop=True)
            time.sleep(1.0)
            i2s.stop()
        except Exception as e:
            i2s.deinit(); btn_ok.deinit(); btn_retry.deinit()
            banner_fail("I2S PLAYBACK ERROR", str(e))
            return False

        print(f"  Heard it? → {GREEN}D0{RST} proceed   {YELLOW}D1{RST} try again")
        while True:
            if not btn_ok.value:        # D0 pressed (active low)
                i2s.deinit(); btn_ok.deinit(); btn_retry.deinit()
                banner_pass("I2S Audio — 440 Hz tone confirmed OK")
                return True
            if not btn_retry.value:     # D1 pressed — replay
                time.sleep(0.05)        # debounce
                break
            time.sleep(0.02)


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 2 — live 3D wireframe renderer
# ═══════════════════════════════════════════════════════════════════════════════

def _rot(x, y, z, r, p, w):
    """Rotate point (x,y,z) by roll r, pitch p, yaw w (radians)."""
    cr, sr = math.cos(r), math.sin(r)
    y, z = y * cr - z * sr, y * sr + z * cr          # Rx
    cp, sp = math.cos(p), math.sin(p)
    x, z = x * cp + z * sp, -x * sp + z * cp         # Ry
    cw, sw = math.cos(w), math.sin(w)
    x, y = x * cw - y * sw, x * sw + y * cw           # Rz
    return x, y, z


def _proj(x, y):
    """Orthographic project to grid coords (terminal chars ~2:1 aspect)."""
    return int(CX + x * SCALE * 2), int(CY - y * SCALE)


def _bres(grid, x0, y0, x1, y1, ch):
    """Bresenham line into bytearray grid."""
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        if 0 <= y0 < GH and 0 <= x0 < GW:
            grid[y0][x0] = ch
        if x0 == x1 and y0 == y1:
            break
        e2 = err << 1
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


def _orientation(accel, mag_data):
    """Roll, pitch, yaw from accelerometer + tilt-compensated magnetometer."""
    ax, ay, az = accel
    roll  = math.atan2(ay, az)
    pitch = math.atan2(-ax, math.sqrt(ay * ay + az * az))

    if mag_data:
        mx, my, mz = mag_data
        cr = math.cos(roll);  sr = math.sin(roll)
        cp = math.cos(pitch); sp = math.sin(pitch)
        hx = mx * cp + mz * sp
        hy = mx * sr * sp + my * cr - mz * sr * cp
        yaw = math.atan2(-hy, hx)
    else:
        yaw = 0.0
    return roll, pitch, yaw


def _render(grid, imu, mag, parts, frame):
    """Render one frame into `parts` (list of strings), reusing `grid`."""
    # Read sensors
    accel = imu.acceleration
    gyro  = imu.gyro
    mag_d = mag.magnetic if mag else None

    roll, pitch, yaw = _orientation(accel, mag_d)

    # Clear grid
    for r in range(GH):
        grid[r][:] = _BLANK

    # Draw cube edges
    dot = ord('.')
    for i0, i1 in _CUBE_E:
        v0 = _CUBE_V[i0]
        v1 = _CUBE_V[i1]
        rx0, ry0, rz0 = _rot(v0[0], v0[1], v0[2], roll, pitch, yaw)
        rx1, ry1, rz1 = _rot(v1[0], v1[1], v1[2], roll, pitch, yaw)
        px0, py0 = _proj(rx0, ry0)
        px1, py1 = _proj(rx1, ry1)
        _bres(grid, px0, py0, px1, py1, dot)

    # Draw axes (on top of cube)
    for idx in range(3):
        tx, ty, tz = _AXIS_TIPS[idx]
        rx, ry, rz = _rot(tx, ty, tz, roll, pitch, yaw)
        ox, oy = _proj(0, 0)   # origin doesn't move in screen space
        ax, ay = _proj(rx, ry)
        _bres(grid, ox, oy, ax, ay, _AXIS_CHARS[idx])
        # label at tip
        if 0 <= ay < GH and 0 <= ax < GW:
            grid[ay][ax] = _AXIS_LABEL[idx]

    # Origin marker
    ox, oy = _proj(0, 0)
    if 0 <= oy < GH and 0 <= ox < GW:
        grid[oy][ox] = ord('O')

    # ── Assemble output string ────────────────────────────────────────────
    parts.clear()
    parts.append(HOME)
    parts.append(HIDE_CUR)

    # Title
    parts.append(f"{CYAN}{'=' * GW}{RST}\n")
    title = " 9-DoF Live Orientation "
    lp = (GW - len(title)) // 2
    rp = GW - lp - len(title)
    parts.append(f"{CYAN}{'=' * lp}{WHITE}{title}{CYAN}{'=' * rp}{RST}\n")
    parts.append(f"{CYAN}{'=' * GW}{RST}\n")

    # Render character grid with per-char colour
    for r in range(GH):
        row = grid[r]
        cur = None
        for c in range(GW):
            ch = row[c]
            if ch == 32:   # space
                if cur is not None:
                    parts.append(RST)
                    cur = None
                parts.append(' ')
            else:
                col = _CHAR_COL.get(ch, WHITE)
                if col != cur:
                    parts.append(col)
                    cur = col
                parts.append(chr(ch))
        if cur is not None:
            parts.append(RST)
        parts.append(CLEAR_EOL)
        parts.append('\n')

    # Separator + sensor readout
    parts.append(f"{CYAN}{'-' * GW}{RST}\n")

    axi, ayi, azi = accel
    gxi, gyi, gzi = gyro
    parts.append(f"  {RED}ACCEL{RST}  x:{axi:+8.2f}  y:{ayi:+8.2f}  z:{azi:+8.2f}  m/s{CLEAR_EOL}\n")
    parts.append(f"  {GREEN}GYRO {RST}  x:{gxi:+8.2f}  y:{gyi:+8.2f}  z:{gzi:+8.2f}  dps{CLEAR_EOL}\n")
    if mag_d:
        mxi, myi, mzi = mag_d
        parts.append(f"  {BLUE}MAG  {RST}  x:{mxi:+8.1f}  y:{myi:+8.1f}  z:{mzi:+8.1f}  uT{CLEAR_EOL}\n")
    else:
        parts.append(f"  {DIM}MAG    (not available){RST}{CLEAR_EOL}\n")

    parts.append(f"{CYAN}{'-' * GW}{RST}\n")

    deg = 180.0 / math.pi
    parts.append(
        f"  ROLL {YELLOW}{roll * deg:+7.1f}{RST}   "
        f"PITCH {YELLOW}{pitch * deg:+7.1f}{RST}   "
        f"YAW {YELLOW}{yaw * deg:+7.1f}{RST}{CLEAR_EOL}\n"
    )
    parts.append(
        f"  {DIM}Axes: {RED}X{DIM} {GREEN}Y{DIM} {BLUE}Z{DIM}  "
        f"Cube: wireframe  #{frame}"
        f"  Ctrl-C to stop{RST}{CLEAR_EOL}\n"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print(CLEAR + HOME)
    print(f"{WHITE}{'=' * 50}")
    print(f"  SentientDoor Hardware Verification")
    print(f"  Feather S3 + ISM330DHCX/LIS3MDL FeatherWing")
    print(f"{'=' * 50}{RST}")
    print()

    # ── Shared I2C bus ────────────────────────────────────────────────────
    # Created once and reused by all tests + the live display.
    # Fixes: original code created a new busio.I2C per test, which crashes
    # on CircuitPython because the pins are already claimed.
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
    except Exception as e:
        banner_fail("I2C BUS",
                     f"Could not initialise I2C: {e}",
                     "Check board — are SCL/SDA shorted?")
        _halt()

    # ── Phase 1: hardware tests ───────────────────────────────────────────
    all_ok = True

    if not test_i2s_audio():
        all_ok = False

    if not test_i2c(i2c):
        all_ok = False

    imu, mag = (None, None)
    if all_ok:
        imu, mag = test_imu(i2c)
        if imu is None:
            all_ok = False

    if not test_speech_synthesis():
        all_ok = False

    # ── Final verdict ─────────────────────────────────────────────────────
    banner_result(all_ok)

    if not all_ok:
        print(f"{RED}Fix the failures above, then press the reset button.{RST}")
        _halt()

    # ── Phase 2: live 3D visualisation ────────────────────────────────────
    gc.collect()
    print(f"{GREEN}IMU tests passed — starting live 9-DoF display ...{RST}")
    time.sleep(1.5)
    print(CLEAR)

    # Pre-allocate grid + parts list (reused every frame, less GC pressure)
    grid  = [bytearray(_BLANK) for _ in range(GH)]
    parts = []
    frame = 0

    while True:
        try:
            _render(grid, imu, mag, parts, frame)
            print("".join(parts), end="")
            frame += 1
            if frame % 60 == 0:
                gc.collect()
            time.sleep(0.08)   # ~12 fps target
        except KeyboardInterrupt:
            print(SHOW_CUR + RST)
            print("\nStopped by user.")
            break
        except Exception as e:
            print(f"\n{RED}Render error: {e}{RST}")
            time.sleep(1)


def _halt():
    """Spin forever — user must reset the board."""
    while True:
        time.sleep(10)


main()
