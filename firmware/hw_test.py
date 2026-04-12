"""
Hardware verification for minimal SentientDoor setup:
  - Feather ESP32-S3
  - ISM330DHCX + LIS3MDL FeatherWing (9-DoF IMU) on I2C
  - MAX98357A I2S amplifier on GPIO pins

Run this as code.py on the Feather to verify all hardware works.

Required CircuitPython libraries in /lib:
  - adafruit_ism330dhcx.mpy
  - adafruit_lis3mdl.mpy
  - adafruit_register/  (dependency for both IMU libs)
  - adafruit_bus_device/ (dependency for both IMU libs)
"""

import time
import math
import board
import busio
import audiobusio
import audiocore
import array


# ── I2S pin config for MAX98357A ─────────────────────────────────────────────
# Adjust these to match your wiring.
# These are the default Prop-Maker positions, but you can use any I2S-capable
# pins on the Feather S3. Wire:
#   MAX98357A BCLK  -> Feather pin
#   MAX98357A LRCLK -> Feather pin
#   MAX98357A DIN   -> Feather pin
#   MAX98357A VIN   -> 3.3V or USB (5V for louder output)
#   MAX98357A GND   -> GND
I2S_BCLK  = board.A0
I2S_LRCLK = board.A1
I2S_DATA  = board.A2


def test_i2c_scan():
    """Scan I2C bus and report devices found."""
    print("\n=== I2C Bus Scan ===")
    i2c = busio.I2C(board.SCL, board.SDA)
    while not i2c.try_lock():
        pass
    try:
        addrs = i2c.scan()
        print(f"Found {len(addrs)} device(s): {[hex(a) for a in addrs]}")
        # ISM330DHCX default address: 0x6A (or 0x6B if SDO/SA0 high)
        # LIS3MDL default address: 0x1C (or 0x1E if SDO/SA1 high)
        expected = {0x6A: "ISM330DHCX", 0x6B: "ISM330DHCX (alt)",
                    0x1C: "LIS3MDL", 0x1E: "LIS3MDL (alt)"}
        for addr in addrs:
            name = expected.get(addr, "unknown")
            print(f"  0x{addr:02X} -> {name}")
        if not addrs:
            print("  No devices found! Check wiring and FeatherWing seating.")
            return False
    finally:
        i2c.unlock()
    return True


def test_imu():
    """Read accelerometer, gyroscope, and magnetometer values."""
    print("\n=== IMU Test (ISM330DHCX + LIS3MDL) ===")
    i2c = busio.I2C(board.SCL, board.SDA)

    # -- ISM330DHCX (accel + gyro) --
    try:
        from adafruit_ism330dhcx import ISM330DHCX
        imu = ISM330DHCX(i2c)
        print("ISM330DHCX initialized OK")
    except Exception as e:
        print(f"ISM330DHCX init FAILED: {e}")
        return False

    # -- LIS3MDL (magnetometer) --
    try:
        from adafruit_lis3mdl import LIS3MDL
        mag = LIS3MDL(i2c)
        print("LIS3MDL initialized OK")
    except Exception as e:
        print(f"LIS3MDL init FAILED: {e}")
        mag = None

    print("\nReading 10 samples (1 per second)...")
    print(f"{'accel (m/s2)':>30}  {'gyro (dps)':>30}  {'mag (uT)':>30}")
    print("-" * 95)

    for i in range(10):
        ax, ay, az = imu.acceleration
        gx, gy, gz = imu.gyro

        accel_str = f"({ax:7.2f}, {ay:7.2f}, {az:7.2f})"
        gyro_str  = f"({gx:7.2f}, {gy:7.2f}, {gz:7.2f})"

        if mag:
            mx, my, mz = mag.magnetic
            mag_str = f"({mx:7.2f}, {my:7.2f}, {mz:7.2f})"
        else:
            mag_str = "(n/a)"

        print(f"{accel_str:>30}  {gyro_str:>30}  {mag_str:>30}")
        time.sleep(1)

    # Sanity check: resting accel magnitude should be ~9.8 m/s^2
    ax, ay, az = imu.acceleration
    accel_mag = math.sqrt(ax**2 + ay**2 + az**2)
    print(f"\nAccel magnitude: {accel_mag:.2f} m/s^2 (expect ~9.81 at rest)")
    if 8.0 < accel_mag < 12.0:
        print("Accelerometer: PASS")
    else:
        print("Accelerometer: SUSPECT (magnitude far from 9.81)")

    return True


def test_i2s_audio():
    """Generate a 440 Hz test tone and play it through the MAX98357A."""
    print("\n=== I2S Audio Test (MAX98357A) ===")
    print(f"Pins: BCLK={I2S_BCLK}, LRCLK={I2S_LRCLK}, DATA={I2S_DATA}")

    try:
        i2s = audiobusio.I2SOut(I2S_BCLK, I2S_LRCLK, I2S_DATA)
    except Exception as e:
        print(f"I2SOut init FAILED: {e}")
        return False

    print("I2SOut initialized OK")

    # Generate a 440 Hz sine wave tone (1 second)
    sample_rate = 22050
    tone_hz = 440
    length = sample_rate // tone_hz  # one cycle
    amplitude = 16000  # ~50% of int16 max

    sine_wave = array.array("h", [0] * length)
    for i in range(length):
        sine_wave[i] = int(amplitude * math.sin(2 * math.pi * i / length))

    tone = audiocore.RawSample(sine_wave, sample_rate=sample_rate)

    print(f"Playing 440 Hz tone for 2 seconds...")
    print("(You should hear a steady A4 tone from the speaker)")
    i2s.play(tone, loop=True)
    time.sleep(2)
    i2s.stop()
    print("Playback stopped.")

    # Play a quick chirp pattern to confirm dynamic audio
    print("Playing chirp pattern (3 short beeps)...")
    for _ in range(3):
        i2s.play(tone, loop=True)
        time.sleep(0.15)
        i2s.stop()
        time.sleep(0.15)

    i2s.deinit()
    print("I2S Audio: PASS (if you heard the tone and beeps)")
    return True


def main():
    print("=" * 60)
    print("  SentientDoor Hardware Verification")
    print("  Feather S3 + ISM330DHCX/LIS3MDL + MAX98357A")
    print("=" * 60)

    results = {}

    results["I2C Scan"] = test_i2c_scan()
    results["IMU"]      = test_imu()
    results["I2S Audio"] = test_i2s_audio()

    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name:20s} [{status}]")
    print("=" * 60)

    all_pass = all(results.values())
    if all_pass:
        print("\nAll hardware verified! Ready for integration.")
    else:
        print("\nSome tests failed. Check wiring and libraries.")

    # Keep alive so serial output stays visible
    while True:
        time.sleep(10)


main()
