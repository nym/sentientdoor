"""
TTS pipeline: text → ElevenLabs API → WAV file on flash → I2S playback.

WAV writing strategy
--------------------
ElevenLabs returns raw PCM (no header). We need a proper RIFF WAV file so
that CircuitPython's audiocore.WaveFile can play it. We don't know the PCM
size until after streaming completes, so we use a two-file approach:

  1. Stream raw PCM to /tts_tmp.pcm in 4 KB chunks (never loads full audio
     into RAM).
  2. Write /tts_tmp.wav = 44-byte WAV header + PCM data copied from the
     temp file in chunks.
  3. Delete /tts_tmp.pcm.
  4. Play /tts_tmp.wav via I2S.

This uses only "wb" and "rb" file modes, which are reliably supported by
CircuitPython's FatFS layer. The "r+b" seek-and-patch approach was removed
because it is not consistently supported across CircuitPython versions.

I2S pins
--------
Configured in settings.toml as PIN_I2S_BCLK / PIN_I2S_LRCLK / PIN_I2S_DATA.
Verify against Adafruit's pinout diagram for your board revision before boot.
"""

import os
import struct
import board
import digitalio
import audiobusio
import audiocore
import json
import ssl
import socketpool
import wifi
import adafruit_requests
import network


ELEVENLABS_URL  = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
AUDIO_FORMAT    = "pcm_22050"   # raw 16-bit PCM, mono, 22050 Hz
SAMPLE_RATE     = 22050
CHANNELS        = 1
BITS_PER_SAMPLE = 16
WAV_PATH        = "/tts_tmp.wav"
PCM_PATH        = "/tts_tmp.pcm"
STREAM_CHUNK    = 4096


def _wav_header(data_size):
    """44-byte RIFF WAV header for 22050 Hz 16-bit mono PCM."""
    byte_rate   = SAMPLE_RATE * CHANNELS * BITS_PER_SAMPLE // 8
    block_align = CHANNELS * BITS_PER_SAMPLE // 8
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, CHANNELS, SAMPLE_RATE, byte_rate, block_align, BITS_PER_SAMPLE,
        b"data", data_size,
    )


class TTSPlayer:

    def __init__(self, settings, session=None):
        self._settings = settings

        api_key = settings.get("ELEVENLABS_API_KEY", "")
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY is missing from settings.toml")
        self._api_key = api_key

        persona        = settings.get("PERSONA", "enthusiast")
        self._voice_id = settings.get(f"VOICE_ID_{persona.upper()}", "")

        pwr_pin = getattr(board, settings.get("PIN_POWER_ENABLE", "A0"))
        self._power = digitalio.DigitalInOut(pwr_pin)
        self._power.direction = digitalio.Direction.OUTPUT
        self._power.value = False

        bclk  = getattr(board, settings.get("PIN_I2S_BCLK",  "A0"))
        lrclk = getattr(board, settings.get("PIN_I2S_LRCLK", "A1"))
        data  = getattr(board, settings.get("PIN_I2S_DATA",  "A2"))
        self._i2s = audiobusio.I2SOut(bclk, lrclk, data)

        if session is not None:
            self._session = session
        else:
            pool = socketpool.SocketPool(wifi.radio)
            self._session = adafruit_requests.Session(pool, ssl.create_default_context())

    # ── Public interface ──────────────────────────────────────────────────────

    def speak(self, text, sensor_manager=None, event_queue=None, lights=None, servo=None, display=None):
        """
        Synthesise `text` and play it. Sensors, LEDs, and servo are all updated
        during playback so nothing blocks the audio loop.
        If `display` is provided the text is shown on-screen immediately (before
        the audio fetch) so it is always visible even if the speaker is silent.
        Returns True on success, False on any error.
        """
        if not text or not self._voice_id:
            print("TTS: no text or voice_id configured — skipping")
            return False

        if display is not None:
            display.show_text(text)

        if not network.ensure_connected(self._settings):
            print("TTS: no network — skipping")
            return False

        try:
            if not self._fetch_to_file(text):
                return False

            self._play(sensor_manager, event_queue, lights, servo)
            return True
        finally:
            if display is not None:
                display.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _fetch_to_file(self, text):
        """
        Stream raw PCM from ElevenLabs to PCM_PATH, then write WAV_PATH with
        correct header. Uses only "wb"/"rb" modes — no seek required.
        Returns True on success.
        """
        url     = ELEVENLABS_URL.format(voice_id=self._voice_id)
        headers = {
            "xi-api-key": self._api_key,
            "content-type": "application/json",
            "accept": "application/octet-stream",
        }
        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2",
            "output_format": AUDIO_FORMAT,
            "voice_settings": {"stability": 0.55, "similarity_boost": 0.80},
        }

        try:
            resp = self._session.post(url, headers=headers,
                                      data=json.dumps(payload), timeout=30)
        except Exception as e:  # noqa: BLE001
            print(f"TTS fetch error: {e}")
            return False

        if resp.status_code != 200:
            print(f"TTS API {resp.status_code}: {resp.text[:80]}")
            return False

        # ── Pass 1: stream PCM to temp file ──────────────────────────────────
        total_pcm = 0
        try:
            with open(PCM_PATH, "wb") as f:
                for chunk in resp.iter_content(chunk_size=STREAM_CHUNK):
                    if chunk:
                        f.write(chunk)
                        total_pcm += len(chunk)
        except Exception as e:  # noqa: BLE001
            print(f"TTS PCM stream error: {e}")
            return False

        if total_pcm == 0:
            print("TTS: received empty audio response")
            return False

        # ── Pass 2: write WAV = header + PCM ─────────────────────────────────
        try:
            with open(WAV_PATH, "wb") as wav:
                wav.write(_wav_header(total_pcm))
                with open(PCM_PATH, "rb") as pcm:
                    while True:
                        chunk = pcm.read(STREAM_CHUNK)
                        if not chunk:
                            break
                        wav.write(chunk)
        except Exception as e:  # noqa: BLE001
            print(f"TTS WAV write error: {e}")
            return False
        finally:
            try:
                os.remove(PCM_PATH)
            except OSError:
                pass

        print(f"TTS: {total_pcm / (SAMPLE_RATE * 2):.1f}s of audio ready")
        return True

    def _play(self, sensor_manager, event_queue, lights=None, servo=None):
        """Play WAV_PATH via I2S, updating sensors, LEDs, and servo each tick."""
        if lights is not None:
            lights.start_speaking()
        if servo is not None:
            servo.start_speaking()
        self._power.value = True
        try:
            with open(WAV_PATH, "rb") as f:
                wav = audiocore.WaveFile(f)
                self._i2s.play(wav)
                while self._i2s.playing:
                    if sensor_manager is not None:
                        ev = sensor_manager.poll()
                        if ev is not None and event_queue is not None:
                            event_queue.put(ev)
                    if lights is not None:
                        lights.update()
                    if servo is not None:
                        servo.update()
        except Exception as e:  # noqa: BLE001
            print(f"TTS playback error: {e}")
        finally:
            self._power.value = False
            if lights is not None:
                lights.stop_speaking()
            if servo is not None:
                servo.stop_speaking()
