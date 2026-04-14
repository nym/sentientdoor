# SentientDoor — Setup Guide

## Hardware

| Component | Part |
|---|---|
| Microcontroller | Adafruit Feather ESP32-S3 |
| IMU | ISM330DHCX + LIS3MDL FeatherWing (stacked on Feather) |
| I2S amp | DFRobot MAX98357 I2S Amplifier Module |
| Speech synth | DFRobot Speech Synthesis Mobile V2.2.0 |
| Door sensor | Magnetic reed switch (normally-closed) |
| Presence sensor | PIR sensor module |
| LEDs | NeoPixel RGB strip |

---

## 1. Install CircuitPython on the Feather ESP32-S3

1. Download the latest **Feather ESP32-S3** `.uf2` from [circuitpython.org/downloads](https://circuitpython.org/downloads) (search "Feather ESP32-S3").
2. Hold the **BOOT** button on the Feather, press and release **RESET**, then release BOOT.  
   The board mounts as a drive called `FTHS2BOOT` (or similar).
3. Drag the `.uf2` file onto that drive.
4. The board reboots automatically and mounts as `CIRCUITPY`.

---

## 2. Install circup

circup manages CircuitPython libraries the same way pip manages Python packages.

```sh
pip install circup
```

With the board connected and mounted as `CIRCUITPY`, install all required libraries in one shot:

```sh
circup install adafruit-lsm6ds adafruit-lis3mdl adafruit-register \
    adafruit-bus-device adafruit-requests adafruit-ntp neopixel \
    adafruit-motor adafruit-st7789 adafruit-display-text
```

Libraries land in `/Volumes/CIRCUITPY/lib/` automatically.

To update libraries later:

```sh
circup update
```

---

## 3. Wiring

### ISM330DHCX + LIS3MDL FeatherWing (IMU)

Stack directly on the Feather — no wires needed.  
The FeatherWing connects to the Feather's I2C bus (SCL/SDA) via the header pins.

### DFRobot MAX98357 I2S Amplifier

| MAX98357 pin | Feather ESP32-S3 |
|---|---|
| VCC | 3V or 5V (5V = louder) |
| GND | GND |
| BCLK | A0 |
| LRC | A1 |
| DIN | A2 |
| SD | leave floating (always on), or wire to a GPIO and set `PIN_POWER_ENABLE` |
| GAIN | leave floating (15 dB), GND = 12 dB |
| SPK+ / SPK− | speaker + / − |

### DFRobot Speech Synthesis Mobile V2.2.0

Set the switch on the module to **UART** before wiring.

| Speech synth pin | Feather ESP32-S3 |
|---|---|
| VCC | 5V |
| GND | GND |
| TX (module) | RX (Feather) |
| RX (module) | TX (Feather) |

### Magnetic Reed Switch (door open/close)

| Reed switch | Feather ESP32-S3 |
|---|---|
| Pin 1 | D6 |
| Pin 2 | GND |

D6 is configured as INPUT with internal pull-up.  
Normally-closed switch: magnet present = LOW (door closed), magnet gone = HIGH (door open).

### PIR Sensor

| PIR pin | Feather ESP32-S3 |
|---|---|
| VCC | 5V (check your module — most need 5V) |
| GND | GND |
| OUT | D9 |

### NeoPixel Strip

| NeoPixel | Feather ESP32-S3 |
|---|---|
| VCC | 5V |
| GND | GND |
| DIN | D5 |

### Hardware Test Buttons (for `code.py` verification only)

Wire two momentary push-buttons normally-open to GND:

| Button | Feather pin | Function |
|---|---|---|
| Proceed | D0 | "I heard the tone — pass" |
| Try again | D1 | "Play the tone again" |

---

## 4. Configure settings.toml

Copy the example file and fill in your credentials:

```sh
cp firmware/settings.toml.example firmware/settings.toml
```

Open `firmware/settings.toml` and set at minimum:

```toml
WIFI_SSID         = "your-network"
WIFI_PASSWORD     = "your-password"
ANTHROPIC_API_KEY = "sk-ant-..."
ELEVENLABS_API_KEY = "your-key"
PERSONA           = "unreliable_narrator"   # or "bouncer" / "ken"
```

Voice IDs are optional — ElevenLabs will use a default voice if left blank.  
`settings.toml` is `.gitignore`d and must never be committed.

---

## 5. Copy firmware files

### Hardware verification (run this first)

Copy just `code.py` to verify all hardware before deploying the full app:

```sh
cp firmware/code.py /Volumes/CIRCUITPY/code.py
```

On boot it will:
1. Play a 440 Hz tone through the MAX98357 — press **D0** if you hear it, **D1** to replay
2. Scan the I2C bus for the ISM330DHCX and LIS3MDL
3. Run accel/gyro/mag sanity checks
4. Send "hello cruel world" to the speech synthesis module and wait for the reply

If everything passes it drops into a live 9-DoF wireframe display on the serial console.

### Full application

Once hardware is verified, copy all firmware files:

```sh
cp firmware/settings.toml  /Volumes/CIRCUITPY/settings.toml
cp firmware/code2.py       /Volumes/CIRCUITPY/code.py
cp firmware/context.py     /Volumes/CIRCUITPY/context.py
cp firmware/display.py     /Volumes/CIRCUITPY/display.py
cp firmware/events.py      /Volumes/CIRCUITPY/events.py
cp firmware/knock.py       /Volumes/CIRCUITPY/knock.py
cp firmware/lights.py      /Volumes/CIRCUITPY/lights.py
cp firmware/llm.py         /Volumes/CIRCUITPY/llm.py
cp firmware/network.py     /Volumes/CIRCUITPY/network.py
cp firmware/reflexes.py    /Volumes/CIRCUITPY/reflexes.py
cp firmware/sensors.py     /Volumes/CIRCUITPY/sensors.py
cp firmware/state.py       /Volumes/CIRCUITPY/state.py
cp firmware/tts.py         /Volumes/CIRCUITPY/tts.py
cp -r personas/            /Volumes/CIRCUITPY/personas/
```

Or all at once using the VS Code file list:

```sh
while IFS= read -r f; do
  dest="/Volumes/CIRCUITPY/$(basename "$f")"
  cp "$f" "$dest"
done < .vscode/cpfiles.txt
cp -r personas/ /Volumes/CIRCUITPY/personas/
```

---

## 6. Monitor the serial console

```sh
# macOS — find the port first:
ls /dev/cu.usbmodem*

# Then connect (replace with your port):
screen /dev/cu.usbmodem101 115200
```

Or use the [Mu editor](https://codewith.mu/) which auto-detects the board.

Press **CTRL-D** in the serial console to soft-reboot the board after copying new files.  
Press **CTRL-C** to interrupt a running program.
