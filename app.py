"""Streamlit UI for the watermark creation tool.  Run with:  streamlit run app.py"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import streamlit as st
from PIL import Image

from watermarker import POSITIONS, WatermarkSettings, watermark_image
from watermarker import documents as docs
from watermarker.fonts import system_fonts

PREVIEW_MAX_PX = 1400
DEFAULT_FONT = "Default (built-in)"

st.set_page_config(page_title="Watermark Studio", page_icon="💧", layout="wide")


# --------------------------------------------------------------------------- cached helpers

@st.cache_data(show_spinner=False)
def read_font(path: str) -> bytes:
    return Path(path).read_bytes()


@st.cache_data(show_spinner="Converting document to PDF…")
def cached_to_pdf(name: str, data: bytes) -> bytes:
    return docs.to_pdf(name, data)


@st.cache_data(show_spinner=False)
def cached_page_count(pdf: bytes) -> int:
    return docs.pdf_page_count(pdf)


@st.cache_data(show_spinner=False)
def cached_preview_base(name: str, data: bytes, page: int) -> Image.Image:
    """Downscaled original used for live previews (full-res is only rendered on download)."""
    if docs.file_category(name) == "image":
        img = docs.open_image(data)
    else:
        img = docs.render_pdf_page(cached_to_pdf(name, data), page).convert("RGBA")
    img.thumbnail((PREVIEW_MAX_PX, PREVIEW_MAX_PX))
    return img


# --------------------------------------------------------------------------- sidebar: watermark settings

def sidebar_settings() -> WatermarkSettings:
    sb = st.sidebar
    sb.header("💧 Watermark")
    s = WatermarkSettings()

    s.kind = "text" if sb.radio("Watermark type", ["Text", "Image"], horizontal=True) == "Text" else "image"

    if s.kind == "text":
        s.text = sb.text_area("Text", "CONFIDENTIAL", height=80,
                              help="Multiple lines are supported.")
        fonts = system_fonts()
        choice = sb.selectbox("Font", [DEFAULT_FONT, *fonts],
                              help="Fonts installed on this computer. Type to search.")
        custom = sb.file_uploader("…or upload a font (.ttf / .otf)", type=["ttf", "otf", "ttc"])
        if custom is not None:
            s.font_bytes = custom.getvalue()
        elif choice != DEFAULT_FONT:
            s.font_bytes = read_font(fonts[choice])
        s.color = sb.color_picker("Color", "#808080", help="Mid-grey shows up on both light and dark backgrounds.")
    else:
        logo = sb.file_uploader("Watermark image (PNG with transparency works best)",
                                type=sorted(docs.IMAGE_EXTS))
        if logo is not None:
            s.image_bytes = logo.getvalue()
            sb.image(logo, width=140)
        s.remove_white_bg = sb.checkbox("Make white background transparent",
                                        help="Useful for logos saved as JPG on a white background.")

    sb.divider()
    sb.subheader("Appearance")
    s.size = sb.slider("Size (% of page width)", 2, 100, 40 if s.kind == "text" else 25)
    s.opacity = sb.slider("Opacity (%)", 0, 100, 35)

    sb.divider()
    sb.subheader("Layout")
    tiled = sb.radio("Placement", ["Single", "Repeated (tiled)"], horizontal=True) != "Single"
    s.mode = "tiled" if tiled else "single"
    s.rotation = sb.slider("Rotation (°)", -180, 180, 30 if tiled else 0, key=f"rot_{s.mode}",
                           help="Positive = counter-clockwise. Try 30–45° for a slanted pattern.")
    if tiled:
        s.spacing_x = sb.slider("Horizontal gap (% of width)", 0, 100, 12)
        s.spacing_y = sb.slider("Vertical gap (% of height)", 0, 100, 12)
        s.stagger = sb.checkbox("Stagger rows (brick pattern)", value=True)
    else:
        s.position = sb.selectbox("Position", POSITIONS, index=POSITIONS.index("center"),
                                  format_func=lambda p: p.replace("-", " ").title())
        s.margin = sb.slider("Edge margin (%)", 0, 25, 3)
    return s


# --------------------------------------------------------------------------- output generation

def output_name(name: str, ext: str) -> str:
    return f"{Path(name).stem}_watermarked.{ext}"


def process_file(name: str, data: bytes, s: WatermarkSettings, img_fmt: str | None,
                 quality: int, flatten: bool) -> bytes:
    """Full-resolution watermarking of one file."""
    if docs.file_category(name) == "image":
        out = watermark_image(docs.open_image(data), s)
        return docs.save_image(out, img_fmt or _same_format(name), quality)
    return docs.watermark_pdf(cached_to_pdf(name, data), s, flatten=flatten)


def process_name(name: str, img_fmt: str | None) -> str:
    if docs.file_category(name) == "image":
        return output_name(name, docs.IMAGE_FORMATS[img_fmt or _same_format(name)])
    return output_name(name, "pdf")


def _same_format(name: str) -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    return {"jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP", "bmp": "BMP",
            "tif": "TIFF", "tiff": "TIFF"}.get(ext, "PNG")  # png/gif → PNG


def mime_for(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1]
    return {"pdf": "application/pdf", "jpg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "bmp": "image/bmp", "tiff": "image/tiff"}.get(ext, "application/octet-stream")


# --------------------------------------------------------------------------- main page

def main() -> None:
    s = sidebar_settings()

    st.title("Watermark Studio")
    st.caption("Add text or logo watermarks to images, PDFs and text documents — "
               "a single stamp or a repeated, slanted pattern.")

    uploads = st.file_uploader(
        "Upload files", type=docs.ALL_EXTS, accept_multiple_files=True,
        help="Images: " + ", ".join(sorted(docs.IMAGE_EXTS)) +
             " · Documents: pdf, docx, " + ", ".join(sorted(docs.TEXT_EXTS)))

    if not uploads:
        st.info("⬆️ Upload one or more files to get started. Configure the watermark in the sidebar.")
        return
    if s.kind == "image" and not s.image_bytes:
        st.warning("Upload a watermark image in the sidebar (or switch the type to Text).")
        return

    files = [(u.name, u.getvalue()) for u in uploads]
    has_images = any(docs.file_category(n) == "image" for n, _ in files)
    has_docs = any(docs.file_category(n) != "image" for n, _ in files)

    # ---- output options
    with st.expander("Output options", expanded=False):
        img_fmt, quality, flatten = None, 92, False
        if has_images:
            choice = st.selectbox("Image output format", ["Same as input", *docs.IMAGE_FORMATS])
            img_fmt = None if choice == "Same as input" else choice
            quality = st.slider("JPEG / WEBP quality", 50, 100, 92)
        if has_docs:
            st.caption("Documents (PDF, DOCX, TXT, …) are always exported as PDF.")
            flatten = st.checkbox(
                "Flatten PDF pages to images",
                help="Makes the watermark much harder to remove, but text is no longer selectable "
                     "and file size grows.")

    # ---- preview
    names = [n for n, _ in files]
    current = st.selectbox("Preview", names) if len(files) > 1 else names[0]
    data = dict(files)[current]
    page = 0
    if docs.file_category(current) != "image":
        n_pages = cached_page_count(cached_to_pdf(current, data))
        if n_pages > 1:
            page = st.number_input(f"Page (of {n_pages})", 1, n_pages, 1) - 1

    try:
        base = cached_preview_base(current, data, page)
        preview = watermark_image(base, s)
    except Exception as exc:  # bad font, corrupt image, etc.
        st.error(f"Could not render watermark: {exc}")
        return

    left, right = st.columns(2)
    left.image(base, caption="Original", width="stretch")
    right.image(preview, caption="Watermarked preview", width="stretch")

    # ---- downloads (rendered at full resolution only when clicked)
    st.subheader("Download")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            f"⬇️ Download {current}",
            data=lambda: process_file(current, data, s, img_fmt, quality, flatten),
            file_name=process_name(current, img_fmt),
            mime=mime_for(process_name(current, img_fmt)),
            type="primary", width="stretch")
    if len(files) > 1:
        with col2:
            st.download_button(
                f"🗜️ Download all {len(files)} files (.zip)",
                data=lambda: build_zip(files, s, img_fmt, quality, flatten),
                file_name="watermarked.zip", mime="application/zip", width="stretch")


def build_zip(files, s, img_fmt, quality, flatten) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            zf.writestr(process_name(name, img_fmt),
                        process_file(name, data, s, img_fmt, quality, flatten))
    return buf.getvalue()


if __name__ == "__main__":  # streamlit runs the script as __main__
    main()
