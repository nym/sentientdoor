"""
TTS pipeline: text → ElevenLabs API → WAV → I2S playback via Prop-Maker FeatherWing.

Flow
----
1. `speak(text)` is called with the LLM's response string
2. POST to ElevenLabs /v1/text-to-speech/{voice_id} requesting PCM/WAV output
3. Write the WAV bytes to a temp file on the CIRCUITPY flash (/tts_tmp.wav)
4. Enable the Prop-Maker power pin, play via I2S, disable power pin when done

Audio spec
----------
ElevenLabs is asked for 22050 Hz, 16-bit, mono PCM. The LIS3DH I2S bus on
the Prop-Maker FeatherWing drives the Class D amplifier directly — no
separate amp board needed.

Prop-Maker FeatherWing I2S pins (Feather ESP32-S3)
---------------------------------------------------
  BCLK  → board.I2S_BCLK  (GPIO 13 on ESP32-S3 Feather)
  LRCLK → board.I2S_LRCLK (GPIO 12)
  DATA  → board.I2S_DATA   (GPIO 11)
  PWR   → PIN_POWER_ENABLE (default A0, configurable in settings.toml)
"""

import board
import digitalio
import audiobusio
import audiocore
import json
import ssl
import wifi
import socketpool
import adafruit_requests


ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

# Requested audio format — ElevenLabs returns WAV when output_format is set
AUDIO_OUTPUT_FORMAT = "pcm_22050"   # 22050 Hz mono 16-bit PCM (ElevenLabs format ID)
SAMPLE_RATE = 22050
TMP_PATH = "/tts_tmp.wav"


class TTSPlayer:

    def __init__(self, settings):
        self._api_key  = settings["ELEVENLABS_API_KEY"]
        persona        = settings.get("PERSONA", "enthusiast")
        self._voice_id = settings.get(f"VOICE_ID_{persona.upper()}", "")

        # Prop-Maker power enable
        pwr_pin = getattr(board, settings.get("PIN_POWER_ENABLE", "A0"))
        self._power = digitalio.DigitalInOut(pwr_pin)
        self._power.direction = digitalio.Direction.OUTPUT
        self._power.value = False   # off until we need it

        # I2S output — Prop-Maker FeatherWing
        self._i2s = audiobusio.I2SOut(
            board.I2S_BCLK,
            board.I2S_LRCLK,
            board.I2S_DATA,
        )

        # Requests session (reuse Wi-Fi socket pool)
        pool = socketpool.SocketPool(wifi.radio)
        self._session = adafruit_requests.Session(pool, ssl.create_default_context())

    # ── Public interface ──────────────────────────────────────────────────────

    def speak(self, text):
        """
        Convert `text` to speech and play it. Blocks until playback is done.
        Returns True on success, False on any error.
        """
        if not text or not self._voice_id:
            print("TTS: no text or voice_id — skipping")
            return False

        wav_bytes = self._fetch_audio(text)
        if not wav_bytes:
            return False

        self._write_tmp(wav_bytes)
        self._play_tmp()
        return True

    # ── Internal ──────────────────────────────────────────────────────────────

    def _fetch_audio(self, text):
        url = ELEVENLABS_URL.format(voice_id=self._voice_id)
        headers = {
            "xi-api-key": self._api_key,
            "content-type": "application/json",
            "accept": "audio/wav",
        }
        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2",
            "output_format": AUDIO_OUTPUT_FORMAT,
            "voice_settings": {
                "stability": 0.55,
                "similarity_boost": 0.80,
            },
        }
        try:
            resp = self._session.post(
                url,
                headers=headers,
                data=json.dumps(payload),
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"TTS API error {resp.status_code}: {resp.text[:80]}")
                return None
            return resp.content   # raw bytes
        except Exception as e:  # noqa: BLE001
            print(f"TTS fetch failed: {e}")
            return None

    def _write_tmp(self, data):
        with open(TMP_PATH, "wb") as f:
            f.write(data)

    def _play_tmp(self):
        self._power.value = True   # enable amp
        try:
            with open(TMP_PATH, "rb") as f:
                wav = audiocore.WaveFile(f)
                self._i2s.play(wav)
                while self._i2s.playing:
                    pass
        except Exception as e:  # noqa: BLE001
            print(f"TTS playback error: {e}")
        finally:
            self._power.value = False   # disable amp — saves power
