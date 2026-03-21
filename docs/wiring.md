# Wiring Guide

## Stack overview

Three boards, zero breakout wires between them:

```
[ Speaker ]
     |  PicoBlade connector
[ Prop-Maker FeatherWing ]   ← stacks directly on top of the Feather
[ Feather ESP32-S3 ]
     |  USB-C (power / programming)
[ LiPo battery ]             ← JST connector on the Feather underside
```

The Prop-Maker FeatherWing plugs into the standard Feather header — no soldering required beyond the headers themselves (which come pre-soldered on both boards from Adafruit).

---

## Connections you need to make

### Speaker

Plug the mini oval speaker's PicoBlade connector directly into the Prop-Maker FeatherWing's speaker port. Polarity matters — the connector is keyed. Do not reverse it.

```
Speaker 8Ω 1W  →  Prop-Maker FeatherWing speaker port (PicoBlade, left side of board)
```

### Magnetic reed switch (door closed/open detection)

A normally-closed reed switch. When the door is shut, the magnet holds the switch closed (circuit complete = LOW). When the door opens, the magnet moves away, the switch opens (floating → pulled HIGH by the Feather's internal pull-up).

```
Reed switch pin 1  →  Feather D6
Reed switch pin 2  →  Feather GND
```

The firmware configures D6 as INPUT with PULL_UP. No external resistor needed.

If your reed switch is normally-open instead of normally-closed, invert the logic in `sensors.py` (`ReedSwitch.__init__`: change `not self._io.value` to `self._io.value`).

### PIR / proximity sensor

Most PIR modules have three pins: VCC, GND, OUT.

```
PIR VCC  →  Feather 3V or 5V (check your module's datasheet — most want 5V)
PIR GND  →  Feather GND
PIR OUT  →  Feather D9
```

D9 is configured as a digital input (no pull required — PIR modules drive the line actively).

For a distance-sensing alternative (e.g. HC-SR04 ultrasonic or VL53L0X ToF), you will need to modify `ProximitySensor` in `sensors.py`. The firmware currently treats proximity as a binary present/absent signal; a threshold distance can be added in `sensors.py`.

### LiPo battery

Plug into the JST-PH connector on the underside of the Feather. The Feather has an onboard charger — it will charge the battery when USB is connected and run from the battery when USB is absent.

Capacity: 500mAh is adequate for a door that wakes on events. If the door is in a busy location (many events per hour), 1000mAh gives comfortable margin.

---

## Pin reference

| Signal           | Feather ESP32-S3 pin | Set in settings.toml       |
|------------------|----------------------|----------------------------|
| Reed switch      | D6                   | `PIN_REED_SWITCH = "D6"`   |
| PIR sensor       | D9                   | `PIN_PIR = "D9"`           |
| Prop-Maker power | A0                   | `PIN_POWER_ENABLE = "A0"`  |
| I2S BCLK         | GPIO 13              | hardcoded (`board.I2S_BCLK`)  |
| I2S LRCLK        | GPIO 12              | hardcoded (`board.I2S_LRCLK`) |
| I2S DATA         | GPIO 11              | hardcoded (`board.I2S_DATA`)  |
| LIS3DH (accel)   | SCL/SDA (I2C)        | auto-discovered by driver  |

The LIS3DH on the Prop-Maker FeatherWing is connected to the Feather's I2C bus internally — no wires needed.

---

## Mounting

### Enclosure

The stack (Feather + Prop-Maker + speaker) fits inside a small project box. Suggested dimensions: 80×50×30mm minimum. Drill or cut:
- A speaker grille hole (oval ~40×25mm) aligned with the speaker cone
- A small cable entry for the reed switch wires and PIR wires
- A USB-C access port if you want to reprogram without opening the box

### Door placement

- Mount the enclosure on the **interior face** of the door, near the top (away from the handle, where impact forces are lower).
- Route the reed switch wires along the door edge to the frame; mount the magnet on the frame opposite the switch.
- Mount the PIR sensor separately on the wall or frame so it has a clear view of the approach path — PIR sensors require line-of-sight and do not work well inside an enclosure.

### Accelerometer orientation

The LIS3DH on the Prop-Maker FeatherWing should be mounted with the board **parallel to the door face** (flat against it). Knock detection uses the axis perpendicular to the door surface; lean detection uses the horizontal axes. If the board is rotated 90°, swap the axis references in `AccelDetector._check_lean`.

---

## Checklist before first boot

- [ ] Feather + Prop-Maker headers aligned and fully seated
- [ ] Speaker PicoBlade connector inserted (keyed — won't go in backwards)
- [ ] Reed switch wired to D6 and GND
- [ ] PIR wired to D9, GND, and appropriate VCC
- [ ] Battery connected (or USB-C power present)
- [ ] `settings.toml` on the CIRCUITPY drive with valid Wi-Fi credentials and API keys
- [ ] Persona selected in `settings.toml`
- [ ] Voice IDs filled in for the chosen persona
