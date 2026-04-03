"""
Optional TFT display — echoes spoken text to screen.

Useful as a fallback when the speaker is not working, or as a
visual complement to speech. Leave TFT_CS blank to disable entirely.

Tested against Adafruit's ST7789-based TFT FeatherWings (1.14" 240×135
and 1.3" 240×240). For other drivers swap adafruit_st7789 for the
appropriate library and update the constructor call.

Settings
--------
TFT_CS         = "D10"   # SPI chip-select pin; blank = disabled
TFT_DC         = "D9"    # data/command pin
TFT_RESET      = ""      # hardware reset pin (optional)
TFT_BACKLIGHT  = ""      # backlight pin driven HIGH (optional)
TFT_WIDTH      = 240
TFT_HEIGHT     = 135
TFT_ROTATION   = 270     # 0 / 90 / 180 / 270
"""

import board
import displayio
import terminalio
from adafruit_display_text import label


FONT       = terminalio.FONT
CHAR_W     = 6    # terminalio.FONT fixed glyph width  (pixels)
CHAR_H     = 14   # terminalio.FONT fixed glyph height (pixels)
PADDING    = 6
TEXT_COLOR = 0xFFFFFF
BG_COLOR   = 0x000000


def _word_wrap(text, cols):
    """Break text into lines of at most `cols` characters."""
    words = text.split(" ")
    lines = []
    line = ""
    for word in words:
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= cols:
            line += " " + word
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return "\n".join(lines)


class TFTDisplay:
    """
    Show spoken text on a small SPI TFT.

    If TFT_CS is blank the object is fully inert — all calls are no-ops,
    so the rest of the code never needs to check whether a display exists.
    """

    def __init__(self, settings):
        cs_pin = settings.get("TFT_CS", "")
        if not cs_pin:
            self._display = None
            return

        import busio
        import digitalio
        import adafruit_st7789

        width    = int(settings.get("TFT_WIDTH",    240))
        height   = int(settings.get("TFT_HEIGHT",   135))
        rotation = int(settings.get("TFT_ROTATION", 270))

        displayio.release_displays()

        cs = digitalio.DigitalInOut(getattr(board, cs_pin))
        dc = digitalio.DigitalInOut(getattr(board, settings.get("TFT_DC", "D9")))

        reset_pin = settings.get("TFT_RESET", "")
        reset = digitalio.DigitalInOut(getattr(board, reset_pin)) if reset_pin else None

        bl_pin = settings.get("TFT_BACKLIGHT", "")
        if bl_pin:
            bl = digitalio.DigitalInOut(getattr(board, bl_pin))
            bl.direction = digitalio.Direction.OUTPUT
            bl.value = True

        spi = busio.SPI(board.SCK, board.MOSI)
        bus = displayio.FourWire(spi, command=dc, chip_select=cs, reset=reset)
        self._display = adafruit_st7789.ST7789(
            bus, width=width, height=height, rotation=rotation,
        )

        # columns of text available after padding
        self._cols = (width - 2 * PADDING) // CHAR_W

        # root group: index 0 = solid black background, index 1 = text label
        bg_bitmap = displayio.Bitmap(width, height, 1)
        bg_palette = displayio.Palette(1)
        bg_palette[0] = BG_COLOR
        self._group = displayio.Group()
        self._group.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette))
        self._display.show(self._group)

    # ── Public interface ──────────────────────────────────────────────────────

    def show_text(self, text):
        """Render `text` on the TFT, word-wrapped to fit the screen."""
        if self._display is None:
            return
        self._remove_label()
        wrapped = _word_wrap(text, self._cols)
        lbl = label.Label(
            FONT, text=wrapped, color=TEXT_COLOR,
            x=PADDING, y=PADDING + CHAR_H // 2,
        )
        self._group.append(lbl)

    def clear(self):
        """Remove any text from the screen."""
        if self._display is None:
            return
        self._remove_label()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _remove_label(self):
        # index 0 is the background tile; index 1 (if present) is the label
        if len(self._group) > 1:
            self._group.pop()
