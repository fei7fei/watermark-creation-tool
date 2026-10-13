"""Discover TrueType/OpenType fonts installed on the system."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

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


@lru_cache(maxsize=1)
def system_fonts() -> dict[str, str]:
    """Return {"Family Style": path} for every loadable font, sorted by name."""
    found: dict[str, str] = {}
    for root in FONT_DIRS:
        if not str(root) or not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in FONT_SUFFIXES:
                continue
            try:
                family, style = ImageFont.truetype(str(path), 12).getname()
            except Exception:
                continue  # unreadable or bitmap-only font
            label = f"{family} {style}".strip() if style and style != "Regular" else family
            found.setdefault(label or path.stem, str(path))
    return dict(sorted(found.items(), key=lambda kv: kv[0].lower()))
