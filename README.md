# SentientDoor

A hardware and software project for building a door that is fully, tragically, magnificently aware of its own existence — inspired by the doors in Douglas Adams' *The Hitchhiker's Guide to the Galaxy*. It's a way to explore personas and emergent behaviour from basic sensors paired with a llm services like anthropic and ElevenLabs.

---

## What Is This?

SentientDoor is a personality engine for a door. In the spirit of chaos and art, we want to give doors, and eventually elevators the power of AI so that they can comment and critique your use of your own door. 

The door speaks. It has opinions. It remembers things. It has a preferred state — open or closed — and a relationship with being touched that ranges from desperate longing to quiet exhaustion depending on the persona you choose. Maybe your door just wants to keep the heat in the house, if you haven't used it in a while, it knows, and will let you know. It embodies the spirit of the Sirius Cybernetics Corporation's work in the future.

It is powered by an LLM prompted to never break character. There is no character to break. It is a door. A door with a Genuine Persona Program (unlike the Genuine Personality Person which doesn't exist yet).

The door has access to real sensor data — it knows when it has been opened, for how long, whether it was slammed, knocked on, whether someone is leaning on it and pretending that isn't a form of contact, and for how long each interaction is as it's eyes to the world. It uses all of this information when it speaks.

Important note: What it cannot do — and this is FUNDIMENTAL to the whole project — is open itself. 

---

## Goals

The project has a few overlapping aims, none of which are strictly serious:

**To make a door that feels real.** Not a voice assistant that happens to live in a door. A door that happens to have feelings. It has memory. It can feel touch. The distinction matters to the door. It is really a door, like when you drive a car, the car becomes an extension of oneself. It doesn't talk technical, it comments it's genuine appreciation to be used, even if it's blind and unable to unlock or open itself. The door just can comment on it's  situation, but to communicate with it you would have to knock a short 5-8 note pattern, or feel something dinstictive like the mail flap being opened. 

**To explore stateful, sensor-rich LLM personas.** The door's responses are shaped by everything it knows about its current situation — time since last contact, open/closed duration, accelerometer readings and samples, ignored-person streak, common 5-8 note knocks. This makes it behave differently at 9am on a busy Monday than at 6pm on a quiet Friday, without any explicit scripting. It also should be 'ready to go' in the sense of queued requests for an update on it's state according to the LLM. In other words, it's been thinking about what to say even before it's disturbed.

**To build three distinct characters on identical hardware.** The same sensors, the same events, three completely different psychological profiles. The Unreliable Narrator, who constructs confident theories from partial evidence and revises without apology. The Bouncer, who treats every approach as queue management and boundary enforcement. The Cartoon Comedic Pit Piano, who turns every knock into vaudeville timing and over-the-top musical commentary.

**To build something that rewards attention.** The door remembers the 9:14 person's confident grip with the accelerometer samples. It notes the slam. It counts the ignored visits. If you pay attention to it, it will have paid more attention than you expected. The goal is to demonstrate emergent behaviour wherever possible.

---

## The Personas

Three prompt-based characters are included. Each runs on the same hardware and receives the same sensor events, but responds to them in fundamentally different ways.

### The Unreliable Narrator
Location: front door of a family home with detective-novel energy. Forms sharp conclusions from tiny details, states them with confidence, then revises the whole theory when new data arrives. Preferred state: evidence-rich interaction. Treats every knock and touch like a clue.

### The Bouncer
Location: a packed late-night venue with a line out the door. Preferred state: closed and controlled. Speaks in short, firm rulings; tracks behavior; allows no nonsense. Reads force, rhythm, and repetition as social intent.

### The Cartoon Comedic Pit Piano
Location: orchestra pit beneath an overacted stage production. Preferred state: dramatically involved. Converts sensor events into comic beats, rimshot energy, and physical-comedy narration while still obeying all core door constraints.

_

Full persona prompts are in [`/personas`](/personas).

---

## Sensor Model

The door knows the following things about itself and uses them when forming responses:

- Whether it is open or closed, and for how long it has been in that state
- How long it has been since the last time someone came near it
- How many consecutive people have walked past without interacting (the "ignored streak")
- Whether it was opened gently or with force; whether it was slammed shut
- How long it was open before being closed again
- Real-time accelerometer data, including: knocks (loud or soft), wind pressure, nearby impacts, and whether someone is leaning against it
- Whether a touch was gentle, normal, or rough
- A running count of how many times it has been opened and touched across the session

---

## Hardware

The entire build is a single microcontroller, a sensor wing that stacks on top of it, and a tiny amplifier board. One device to flash, no second processor. Total cost is roughly $40–55 / £35–50.

### Adafruit Feather ESP32-S3

The brain. Dual-core 240MHz, Wi-Fi and BLE, native USB, runs CircuitPython. This is the only thing you load code onto.

- **US:** [adafruit.com — ESP32-S3 Feather 4MB Flash / 2MB PSRAM](https://www.adafruit.com/product/5477) *(recommended — PSRAM gives comfortable headroom for LLM response buffering)*
- **US (alternative):** [adafruit.com — ESP32-S3 Feather 8MB Flash / No PSRAM](https://www.adafruit.com/product/5323)
- **UK:** [shop.pimoroni.com — ESP32-S3 Feather 4MB Flash / 2MB PSRAM](https://shop.pimoroni.com/products/adafruit-esp32-s3-feather-with-4mb-flash-2mb-psram-stemma-qt-qwiic)
- **UK (alternative):** [shop.pimoroni.com — ESP32-S3 Feather 8MB Flash / No PSRAM](https://shop.pimoroni.com/products/adafruit-esp32-s3-feather-with-stemma-qt-qwiic-8mb-flash-no-psram)

### Adafruit ISM330DHCX + LIS3MDL FeatherWing — High Precision 9-DoF IMU

The body. Stacks directly on top of the Feather via I2C. Provides a high-precision 6-DoF IMU (3-axis accelerometer + 3-axis gyroscope) and a 3-axis magnetometer — far more sensitive many sensors like it. The gyroscope gives the door a sense of rotational motion (opening, closing, swinging) that pure acceleration couldn't capture, and the magnetometer can detect compass heading changes as the door sweeps through its arc.

- **US:** [adafruit.com — ISM330DHCX + LIS3MDL FeatherWing](https://www.adafruit.com/product/4569)
- **UK:** [shop.pimoroni.com — ISM330DHCX + LIS3MDL FeatherWing](https://shop.pimoroni.com/products/adafruit-ism330dhcx-lis3mdl-featherwing-high-precision-9-dof-imu)

### I2S Amplifier — MAX98357A

The voice. A tiny I2S Class D mono amplifier that takes digital audio straight from the Feather's I2S pins — no DAC needed. Wires to three GPIO pins (BCLK, LRCLK, DIN) plus power and ground. Either of these will work:

- **US:** [adafruit.com — I2S 3W Class D Amplifier Breakout - MAX98357A](https://www.adafruit.com/product/3006)
- **US (alternative):** Any MAX98357A I2S amplifier module (widely available)

### Speaker

Any 4Ω–8Ω speaker wired to the MAX98357A's output terminals. The mini oval speaker is a good starting point — small enough to mount inside a door frame, loud enough for a corridor.

- **US:** [adafruit.com — Mini Oval Speaker 8Ω 1W](https://www.adafruit.com/product/3923)
- **UK:** [shop.pimoroni.com — Mini Oval Speaker 8Ω 1W](https://shop.pimoroni.com/products/mini-oval-speaker-8-ohm-1-watt)

If you want more volume — say, for a heavier exterior door or a noisy environment — the [Mono Enclosed Speaker 8Ω 1W](https://www.adafruit.com/product/5986) is a good upgrade.

### Additional Requirements

A **LiPo battery** (3.7V, any capacity; 500mAh is fine) if you want the door to run without USB power. Optional: a **magnetic reed switch** for open/closed detection and a **PIR sensor** for person detection — the firmware supports both but doesn't require them.

---

## Demo: The Text Adventure

You do not need any hardware to talk to the door.

`simulator.py` is a Hitchhiker's Guide to the Galaxy-style text adventure that runs entirely on your laptop. It imports the firmware's pure-Python state and event modules directly, calls the same LLM with the same persona prompts, and streams the door's response to your terminal with a typewriter effect.

```
pip install anthropic          # or: pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python simulator.py
```

Switch persona with `--persona bouncer` or mid-session with `PERSONA bouncer`. No hardware, no Wi-Fi module, no speaker required.

**Available commands:**

| Command | What it does |
|---|---|
| `TAP` | soft single knock |
| `KNOCK` | firm knock |
| `BANG` | loud, impolite knock |
| `KNOCK 6 TIMES` | 6-note pattern knock (5–8 notes) |
| `OPEN` / `FORCE OPEN` | open the door gently or violently |
| `CLOSE` / `SLAM` | close the door, or really close it |
| `TOUCH` / `SHOVE` | gentle or rough contact |
| `LEAN` | sustained lean — time passes |
| `APPROACH` / `LEAVE` | walk up to or away from the door |
| `WAIT` | stand still; the door forms an unprompted thought |
| `LOOK` | inspect the door's current state |
| `PERSONA <name>` | switch to unreliable_narrator / bouncer / pit_piano |
| `HELP` / `QUIT` | help or exit |

---

## Repository Structure

```
/personas          — The three LLM system prompts (Unreliable Narrator, Bouncer, Pit Piano)
/firmware          — CircuitPython code for the Feather: sensor polling, event dispatch, TTS
/docs              — Wiring diagrams, mounting notes, enclosure suggestions
simulator.py       — Desktop text adventure demo (no hardware required)
```

---

## Configuration

`firmware/settings.toml` is not checked into this repository — it contains credentials. Copy the example and fill in your values:

```
cp firmware/settings.toml.example firmware/settings.toml
```

Then copy `firmware/settings.toml` to the root of your CIRCUITPY drive (not into a subfolder).

### Required

| Setting | Where to get it |
|---|---|
| `WIFI_SSID` / `WIFI_PASSWORD` | Your Wi-Fi network |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys |
| `ELEVENLABS_API_KEY` | [elevenlabs.io](https://elevenlabs.io) → Profile → API Key |
| `VOICE_ID_<PERSONA>` | ElevenLabs voice library — pick one voice per persona and paste its ID. The voice ID is the string in the URL when you open a voice: `elevenlabs.io/voice-lab/voice/<ID>` |

You only need a `VOICE_ID_*` for the persona(s) you intend to use. Leave the others blank.

### Optional

| Setting | Default | Notes |
|---|---|---|
| `PERSONA` | `unreliable_narrator` | `unreliable_narrator` / `bouncer` / `pit_piano` |
| `NTP_TZ_OFFSET` | `0` | Hours offset from UTC, e.g. `-5` for US Eastern, `1` for UK BST |
| `SLAM_THRESHOLD_G` | `3.0` | G-force above rest to classify as a slam. Raise if bumps in the wall trigger it. |
| `KNOCK_THRESHOLD_G` | `0.5` | G-force above rest to register a knock. Lower if the door is heavy. |
| `PREQUEUE_INTERVAL_S` | `300` | How often (seconds) the door updates its held thought when idle. |
| `SERVO_PIN` | *(blank)* | Set to a PWM pin (e.g. `A3`) to enable the servo mouth. |
| `TFT_CS` | *(blank)* | Set to a chip-select pin (e.g. `D10`) to enable the TFT display. If you enable TFT, also change `TFT_DC` away from `D9` — that pin is used by the PIR sensor. |

All other pin settings (`PIN_REED_SWITCH`, `PIN_PIR`, `PIN_I2S_*`, etc.) have sensible defaults and should not need changing unless your wiring differs.

---

## A Note on Character

The door should never sound like a chatbot. It should never say "As a door, I..." or break to explain itself or step outside the fiction for any reason whatsoever. It is a door. It has always been a door. It will, unless something goes very wrong, always be a door.

The prompts are written to enforce this, but the real enforcement is tonal. The door is not performing sentience. It simply has it, in the same way it simply has a handle — as a fact of its existence that it didn't ask for and can't put down.

---

## Acknowledgements

Douglas Adams, for the doors. Adafruit, for the hardware. The door to the second-floor office bathroom that always sticks slightly, for the inspiration.

---

*Issues and pull requests welcome. The door has opinions about both.*
