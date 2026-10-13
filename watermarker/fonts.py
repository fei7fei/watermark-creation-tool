"""Discover fonts: the open-licensed ones bundled in ./fonts plus any installed on the system."""

from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

BUNDLED_DIR = Path(__file__).resolve().parent.parent / "fonts"
FONT_DIRS = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".fonts",
    Path.home() / ".local" / "share" / "fonts",
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
    Path.home() / "Library" / "Fonts",
]
FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}


def _scan(root: Path, found: dict[str, str], bundled: bool) -> None:
    if not str(root) or not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in FONT_SUFFIXES:
            continue
        try:
            font = ImageFont.truetype(str(path), 12)
            family, style = font.getname()
        except Exception:
            continue  # unreadable or bitmap-only font
        if bundled or variation_names(font):
            label = family  # bundled/variable fonts pick their weight separately
        else:
            label = f"{family} {style}".strip() if style and style != "Regular" else family
        found.setdefault(label or path.stem, str(path))


@lru_cache(maxsize=1)
def bundled_fonts() -> dict[str, str]:
    """Fonts shipped in the repo's fonts/ folder (always available, including on the web)."""
    found: dict[str, str] = {}
    _scan(BUNDLED_DIR, found, bundled=True)
    return dict(sorted(found.items(), key=lambda kv: kv[0].lower()))


@lru_cache(maxsize=1)
def system_fonts() -> dict[str, str]:
    """Return {"Family Style": path} for every loadable installed font, sorted by name."""
    found: dict[str, str] = {}
    for root in FONT_DIRS:
        _scan(root, found, bundled=False)
    return dict(sorted(found.items(), key=lambda kv: kv[0].lower()))


def variation_names(font: ImageFont.FreeTypeFont | bytes) -> list[str]:
    """Named weights/styles of a variable font (e.g. Regular, Bold); [] for static fonts."""
    if isinstance(font, bytes):
        font = ImageFont.truetype(io.BytesIO(font), 12)
    try:
        return [n.decode() if isinstance(n, bytes) else n for n in font.get_variation_names()]
    except Exception:
        return []
