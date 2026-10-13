"""File-type handling: images, PDFs, and text documents (.txt/.md/.docx etc. are converted to PDF)."""

from __future__ import annotations

import html
import io
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph
import pymupdf
from PIL import Image

from .core import WatermarkSettings, build_layer, watermark_image

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "gif"}
PDF_EXTS = {"pdf"}
TEXT_EXTS = {"txt", "md", "csv", "log", "json", "xml", "html", "rtf"}
DOCX_EXTS = {"docx"}
ALL_EXTS = sorted(IMAGE_EXTS | PDF_EXTS | TEXT_EXTS | DOCX_EXTS)

IMAGE_FORMATS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "BMP": "bmp", "TIFF": "tiff"}

# Pixels per PDF point used when rasterising the watermark layer for PDFs (2 = 144 DPI).
PDF_LAYER_SCALE = 2


def file_category(name: str) -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    if ext in IMAGE_EXTS:
        return "image"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in DOCX_EXTS:
        return "docx"
    if ext in TEXT_EXTS:
        return "text"
    raise ValueError(f"Unsupported file type: .{ext}")


# --------------------------------------------------------------------------- images

def save_image(img: Image.Image, fmt: str, quality: int = 92) -> bytes:
    """Encode an RGBA image; formats without alpha are flattened onto white."""
    buf = io.BytesIO()
    if fmt in ("JPEG", "BMP"):
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.getchannel("A"))
        img = flat
    kwargs = {"quality": quality} if fmt in ("JPEG", "WEBP") else {}
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def open_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.seek(0)  # animated GIF/WEBP: first frame only
    return img.convert("RGBA")


# --------------------------------------------------------------------------- text → PDF

_PAGE_CSS = """
body { font-family: sans-serif; font-size: 11pt; line-height: 1.4; }
pre  { font-family: monospace; font-size: 10pt; white-space: pre-wrap; }
table { border-collapse: collapse; }
td, th { border: 1px solid #999; padding: 3px; }
"""


def _html_to_pdf(body: str) -> bytes:
    """Lay out HTML across as many A4 pages as needed using PyMuPDF's Story engine."""
    story = pymupdf.Story(html=body, user_css=_PAGE_CSS)
    page_rect = pymupdf.paper_rect("a4")
    content_rect = page_rect + (54, 54, -54, -54)  # 0.75" margins
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    more = True
    while more:
        device = writer.begin_page(page_rect)
        more, _ = story.place(content_rect)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buf.getvalue()


def text_to_pdf(data: bytes) -> bytes:
    text = data.decode("utf-8", errors="replace")
    return _html_to_pdf(f"<pre>{html.escape(text)}</pre>")


def docx_to_pdf(data: bytes) -> bytes:
    """Convert a .docx to PDF, keeping paragraphs, headings, bold/italic runs and tables."""
    document = docx.Document(io.BytesIO(data))
    parts: list[str] = []

    def runs_html(paragraph) -> str:
        out = []
        for run in paragraph.runs:
            t = html.escape(run.text)
            if run.bold:
                t = f"<b>{t}</b>"
            if run.italic:
                t = f"<i>{t}</i>"
            if run.underline:
                t = f"<u>{t}</u>"
            out.append(t)
        return "".join(out) or "&nbsp;"

    # Walk the body in order so tables appear where they are in the document.
    for block in document.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(block, document)
            style = (p.style.name if p.style is not None else "") or ""
            if style.startswith("Heading") and style[-1:].isdigit():
                lvl = min(int(style[-1]), 6)
                parts.append(f"<h{lvl}>{runs_html(p)}</h{lvl}>")
            elif style == "Title":
                parts.append(f"<h1>{runs_html(p)}</h1>")
            else:
                parts.append(f"<p>{runs_html(p)}</p>")
        elif tag == "tbl":
            t = Table(block, document)
            rows = "".join(
                "<tr>" + "".join(f"<td>{html.escape(c.text)}</td>" for c in row.cells) + "</tr>"
                for row in t.rows)
            parts.append(f"<table>{rows}</table>")
    return _html_to_pdf("".join(parts) or "<p></p>")


def to_pdf(name: str, data: bytes) -> bytes:
    """Return PDF bytes for any non-image document."""
    cat = file_category(name)
    if cat == "pdf":
        return data
    if cat == "docx":
        return docx_to_pdf(data)
    if cat == "text":
        return text_to_pdf(data)
    raise ValueError(f"{name} is not a document")


# --------------------------------------------------------------------------- PDF

def pdf_page_count(pdf: bytes) -> int:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return doc.page_count


def render_pdf_page(pdf: bytes, page_no: int, zoom: float = 1.5) -> Image.Image:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[page_no].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def preview_pdf_page(pdf: bytes, page_no: int, settings: WatermarkSettings) -> Image.Image:
    """Fast preview: rasterise one page and watermark it like an image."""
    return watermark_image(render_pdf_page(pdf, page_no), settings)


def watermark_pdf(pdf: bytes, settings: WatermarkSettings, flatten: bool = False,
                  flatten_dpi: int = 150) -> bytes:
    """Overlay the watermark on every page.

    The original page content stays vector/selectable; the watermark is added as a
    transparent image on top. With `flatten`, each page is rasterised afterwards so the
    watermark can't simply be deleted from the PDF.
    """
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    layer_xrefs: dict[tuple[int, int], int] = {}  # reuse one image per page size

    for page in doc:
        # The layer is drawn for the page as the reader sees it (page.rect), but images are
        # placed in unrotated page space, so derotate the target rect and rotate the image back.
        rect = page.rect
        target = rect * page.derotation_matrix
        size = (round(rect.width * PDF_LAYER_SCALE), round(rect.height * PDF_LAYER_SCALE))
        xref = layer_xrefs.get(size, 0)
        if xref:
            page.insert_image(target, xref=xref, rotate=page.rotation, overlay=True)
        else:
            buf = io.BytesIO()
            build_layer(settings, size).save(buf, format="PNG")
            layer_xrefs[size] = page.insert_image(
                target, stream=buf.getvalue(), rotate=page.rotation, overlay=True)

    if flatten:
        flat = pymupdf.open()
        zoom = flatten_dpi / 72
        for page in doc:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            new_page = flat.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, stream=pix.tobytes("jpeg", jpg_quality=90))
        doc.close()
        doc = flat

    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out
