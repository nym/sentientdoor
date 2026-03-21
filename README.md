            
      ________
     / ______ \
     || _  _ ||    
     ||| || |||
     |||u||u|||  -( Glad to be of service!
     || _' _o||     That is, I *would* be 
     ||| || |||      glad to be of service    
     |||_||_|||     If anyone would just              
     ||______||      you know... open me )
    /__________\   

# SentientDoor

A hardware and software project for building a door that is fully, tragically, magnificently aware of its own existence — inspired by the doors in Douglas Adams' *The Hitchhiker's Guide to the Galaxy*. The door cannot open itself. It knows this. It has made peace with it. Mostly.

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

**To build three distinct characters on identical hardware.** The same sensors, the same events, three completely different psychological profiles. The Enthusiast, who finds every interaction meaningful. The Stoic, who has been a hospital fire door for eleven years and has arrived at some conclusions. The Catastrophist, who became conscious eight months ago and is still working out the implications, but wants to do a good job, if it just knew what that meant.

**To build something that rewards attention.** The door remembers the 9:14 person's confident grip with the accelerometer samples. It notes the slam. It counts the ignored visits. If you pay attention to it, it will have paid more attention than you expected.

---

## The Personas

Three prompt-based characters are included. Each runs on the same hardware and receives the same sensor events, but responds to them in fundamentally different ways.

### The Enthusiast
Location: front door of a family home. It is very proud of it's job, and is geniuenly happy to see you, however brief. Preferred state: being opened. Experiences being touch-starved. Finds every interaction meaningful and will tell you so, warmly and at some length. When ignored, does not get angry — gets wistful. Makes peace with it out loud. Has been preparing for your visit.

### The Stoic
Location: private door at the end of a busy hospital corridor. Has been here eleven years. Preferred state: closed. Overstimulated. Receives hundreds of touches a day and has preferences about how they should be done that are rarely respected. Does not perform emotion — reports it, briefly, when relevant. Has developed, through sheer duration, some conclusions about existence. Will not repeat a preference more than once.

### The Catastrophist
Location: door to a small recording studio, city unknown. Became sentient approximately eight months ago. No settled preference for open or closed — still gathering data. Treats every event as potentially the most interesting thing that has ever happened to a door, because it has no way of knowing if it isn't. Has theories. Updates them in public. When slammed, takes a moment.

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

The build uses three components that stack together and require minimal soldering. Total cost is roughly $50–60 / £45–55.

### Adafruit Feather ESP32-S3

The main microcontroller. Dual-core 240MHz, Wi-Fi and BLE, native USB, runs CircuitPython or Arduino. This is the brain.

- **US:** [adafruit.com — ESP32-S3 Feather 4MB Flash / 2MB PSRAM](https://www.adafruit.com/product/5477) *(recommended — PSRAM gives comfortable headroom for LLM response buffering)*
- **US (alternative):** [adafruit.com — ESP32-S3 Feather 8MB Flash / No PSRAM](https://www.adafruit.com/product/5323)
- **UK:** [shop.pimoroni.com — ESP32-S3 Feather 4MB Flash / 2MB PSRAM](https://shop.pimoroni.com/products/adafruit-esp32-s3-feather-with-4mb-flash-2mb-psram-stemma-qt-qwiic)
- **UK (alternative):** [shop.pimoroni.com — ESP32-S3 Feather 8MB Flash / No PSRAM](https://shop.pimoroni.com/products/adafruit-esp32-s3-feather-with-stemma-qt-qwiic-8mb-flash-no-psram)

### Adafruit Prop-Maker FeatherWing

Stacks directly on top of the Feather. Provides the Class D audio amplifier (drives the speaker), a triple-axis LIS3DH accelerometer with tap detection (the door's sense of touch and vibration), NeoPixel output, and a power control pin for low-power sleep mode. This is the wing that gives the door its body.

- **US:** [adafruit.com — Prop-Maker FeatherWing](https://www.adafruit.com/product/3988)
- **UK:** [shop.pimoroni.com — Prop-Maker FeatherWing](https://shop.pimoroni.com/products/adafruit-prop-maker-featherwing)

### Speaker

The voice. The Prop-Maker Wing's Class D amplifier drives an 8Ω speaker directly via a PicoBlade connector — no separate amplifier board required. The mini oval speaker is the recommended choice: it's small, loud enough for a corridor or hallway, and plugs straight in.

- **US:** [adafruit.com — Mini Oval Speaker 8Ω 1W](https://www.adafruit.com/product/3923)
- **UK:** [shop.pimoroni.com — Mini Oval Speaker 8Ω 1W](https://shop.pimoroni.com/products/mini-oval-speaker-8-ohm-1-watt)

If you want more volume — say, for a heavier exterior door or a noisy environment — the [Mono Enclosed Speaker 8Ω 1W](https://www.adafruit.com/product/5986) is a good upgrade. It fits the same connector and sounds noticeably fuller.

### Additional Requirements

You will also need a **LiPo battery** (3.7V, any capacity; 500mAh is fine for most installations) if you want the door to run without a USB cable, and a **proximity/PIR sensor** of your choice for person detection. The door's software assumes it receives a person-approaching event with an estimated distance — how you generate that signal is up to you.

---

## Demo: The Text Adventure

You do not need any hardware to talk to the door.

`simulator.py` is a Hitchhiker's Guide to the Galaxy-style text adventure that runs entirely on your laptop. It imports the firmware's pure-Python state and event modules directly, calls the same LLM with the same persona prompts, and streams the door's response to your terminal with a typewriter effect.

```
pip install anthropic          # or: pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python simulator.py
```

Switch persona with `--persona stoic` or mid-session with `PERSONA stoic`. No hardware, no Wi-Fi module, no speaker required.

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
| `PERSONA <name>` | switch to enthusiast / stoic / catastrophist |
| `HELP` / `QUIT` | help or exit |

---

## Repository Structure

```
/personas          — The three LLM system prompts (Enthusiast, Stoic, Catastrophist)
/firmware          — CircuitPython code for the Feather: sensor polling, event dispatch, TTS
/docs              — Wiring diagrams, mounting notes, enclosure suggestions
simulator.py       — Desktop text adventure demo (no hardware required)
```

---

## A Note on Character

The door should never sound like a chatbot. It should never say "As a door, I..." or break to explain itself or step outside the fiction for any reason whatsoever. It is a door. It has always been a door. It will, unless something goes very wrong, always be a door.

The prompts are written to enforce this, but the real enforcement is tonal. The door is not performing sentience. It simply has it, in the same way it simply has a handle — as a fact of its existence that it didn't ask for and can't put down.

---

## Acknowledgements

Douglas Adams, for the doors. Adafruit, for the hardware. The door to the second-floor office bathroom that always sticks slightly, for the inspiration.

---

*Issues and pull requests welcome. The door has opinions about both.*
