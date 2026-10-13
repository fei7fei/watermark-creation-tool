"""Core watermark rendering: builds a transparent watermark layer and composites it onto images."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont

POSITIONS = (
    "top-left", "top-center", "top-right",
    "center-left", "center", "center-right",
    "bottom-left", "bottom-center", "bottom-right",
)


@dataclass
class WatermarkSettings:
    """Everything needed to render a watermark, independent of the target file."""

    kind: str = "text"                  # "text" or "image"
    text: str = "CONFIDENTIAL"
    font_bytes: bytes | None = None     # TrueType/OpenType font data; None = Pillow's bundled font
    color: str = "#808080"
    image_bytes: bytes | None = None    # watermark image (logo) data
    remove_white_bg: bool = False       # make near-white pixels of the logo transparent

    size: float = 40.0                  # watermark width as % of the target's width
    opacity: float = 40.0               # 0-100
    rotation: float = 0.0               # degrees, counter-clockwise

    mode: str = "single"                # "single" or "tiled"
    position: str = "center"            # used in single mode
    margin: float = 3.0                 # % of the shorter side, single mode
    spacing_x: float = 15.0             # gap between tiles, % of the target's width
    spacing_y: float = 15.0             # gap between tile rows, % of the target's height
    stagger: bool = True                # offset every other row by half a tile

    _logo_cache: Image.Image | None = field(default=None, repr=False, compare=False)


# --------------------------------------------------------------------------- helpers

def _load_font(settings: WatermarkSettings, px: int) -> ImageFont.FreeTypeFont:
    px = max(1, int(px))
    if settings.font_bytes:
        return ImageFont.truetype(io.BytesIO(settings.font_bytes), px)
    return ImageFont.load_default(px)


def _apply_opacity(img: Image.Image, opacity: float) -> Image.Image:
    alpha = img.getchannel("A").point(lambda a: int(a * opacity / 100))
    img.putalpha(alpha)
    return img


def _logo(settings: WatermarkSettings) -> Image.Image:
    if settings._logo_cache is None:
        logo = Image.open(io.BytesIO(settings.image_bytes)).convert("RGBA")
        if settings.remove_white_bg:
            # Fade out near-white pixels; the soft ramp avoids a halo around JPEG edges.
            r, g, b, a = logo.split()
            darkest = ImageChops.darker(r, ImageChops.darker(g, b))
            keep = darkest.point(lambda v: 0 if v >= 240 else 255 if v <= 190 else (240 - v) * 255 // 50)
            logo.putalpha(ImageChops.multiply(a, keep))
        settings._logo_cache = logo
    return settings._logo_cache


def render_mark(settings: WatermarkSettings, target_width: int) -> Image.Image:
    """Render the unrotated watermark (text or logo) at full alpha, sized for the target."""
    width = max(1, round(target_width * settings.size / 100))

    if settings.kind == "image":
        if not settings.image_bytes:
            raise ValueError("No watermark image provided.")
        logo = _logo(settings)
        height = max(1, round(logo.height * width / logo.width))
        return logo.resize((width, height), Image.LANCZOS)

    text = settings.text or " "
    # Measure at a reference size, then scale the font so the text block fills `width`.
    ref = 200
    l, t, r, b = ImageDraw.Draw(Image.new("L", (1, 1))).multiline_textbbox(
        (0, 0), text, font=_load_font(settings, ref), align="center")
    font = _load_font(settings, ref * width / max(1, r - l))
    l, t, r, b = ImageDraw.Draw(Image.new("L", (1, 1))).multiline_textbbox(
        (0, 0), text, font=font, align="center")
    l, t, r, b = math.floor(l), math.floor(t), math.ceil(r), math.ceil(b)
    pad = max(2, (b - t) // 10)
    mark = Image.new("RGBA", (r - l + 2 * pad, b - t + 2 * pad), (0, 0, 0, 0))
    rgb = ImageColor.getrgb(settings.color)[:3]
    ImageDraw.Draw(mark).multiline_text(
        (pad - l, pad - t), text, font=font, fill=rgb + (255,), align="center")
    return mark


# --------------------------------------------------------------------------- layers

def build_layer(settings: WatermarkSettings, size: tuple[int, int]) -> Image.Image:
    """Return a transparent RGBA layer of `size` containing the positioned watermark(s)."""
    w, h = size
    mark = render_mark(settings, w)

    if settings.mode == "tiled":
        layer = _tiled_layer(settings, mark, w, h)
    else:
        layer = _single_layer(settings, mark, w, h)
    return _apply_opacity(layer, settings.opacity)


def _single_layer(settings: WatermarkSettings, mark: Image.Image, w: int, h: int) -> Image.Image:
    if settings.rotation:
        mark = mark.rotate(settings.rotation, resample=Image.BICUBIC, expand=True)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    margin = round(min(w, h) * settings.margin / 100)
    vert, _, horiz = settings.position.partition("-")
    if settings.position == "center":
        vert, horiz = "center", "center"

    x = {"left": margin, "center": (w - mark.width) // 2, "right": w - mark.width - margin}[horiz]
    y = {"top": margin, "center": (h - mark.height) // 2, "bottom": h - mark.height - margin}[vert]
    layer.paste(mark, (x, y))  # plain paste copies alpha exactly onto the empty layer
    return layer


def _tiled_layer(settings: WatermarkSettings, mark: Image.Image, w: int, h: int) -> Image.Image:
    # Tile an unrotated grid over a square big enough to cover the target at any angle,
    # then rotate the whole grid. This gives the classic evenly-spaced slanted pattern.
    diag = math.ceil(math.hypot(w, h))
    big = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    step_x = mark.width + max(1, round(w * settings.spacing_x / 100))
    step_y = mark.height + max(1, round(h * settings.spacing_y / 100))

    for row, y in enumerate(range(-step_y, diag + step_y, step_y)):
        offset = step_x // 2 if settings.stagger and row % 2 else 0
        for x in range(-step_x + offset, diag + step_x, step_x):
            big.paste(mark, (x, y))  # tiles never overlap, so no masking needed

    if settings.rotation:
        big = big.rotate(settings.rotation, resample=Image.BICUBIC)
    left, top = (diag - w) // 2, (diag - h) // 2
    return big.crop((left, top, left + w, top + h))


# --------------------------------------------------------------------------- public API

def watermark_image(img: Image.Image, settings: WatermarkSettings) -> Image.Image:
    """Return a new RGBA image with the watermark composited on top."""
    base = img.convert("RGBA")
    return Image.alpha_composite(base, build_layer(settings, base.size))
