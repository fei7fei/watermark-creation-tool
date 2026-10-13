# 💧 Watermark Studio

A Streamlit app for adding watermarks to **images, PDFs and text documents**. The watermark can be **text** or an **image** (e.g. a logo), placed **once** or **repeated as a slanted pattern**, with control over opacity, size, rotation, font and color.

| Repeated, slanted text | Single stamp | Repeated logo |
|---|---|---|
| ![tiled](docs/example-tiled.jpg) | ![single](docs/example-single.jpg) | ![logo](docs/example-logo.jpg) |

---

## Quick start

Requires **Python 3.10+**.

```bash
git clone https://github.com/fei7fei/watermark-creation-tool.git
cd watermark-creation-tool

python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

Streamlit opens the app in your browser (usually at http://localhost:8501).

---

## Using the app

1. **Set up the watermark** in the left sidebar.
2. **Upload** one or more files in the main area.
3. Check the **side-by-side preview** (original vs. watermarked). It updates as you move the sliders.
4. Click **Download** to get the watermarked file, or **Download all (.zip)** if you uploaded several.

### Supported input files

| Category | Extensions | Output |
|---|---|---|
| Images | `png` `jpg` `jpeg` `webp` `bmp` `tif` `tiff` `gif` | Same format as input, or choose PNG / JPEG / WEBP / BMP / TIFF |
| PDF | `pdf` | PDF |
| Word | `docx` | PDF |
| Plain text | `txt` `md` `csv` `log` `json` `xml` `html` `rtf` | PDF |

### Watermark options (sidebar)

**Watermark type**
- **Text**: type any text. Multi-line text works and is centred.
  - **Font**: pick any font installed on your computer (the list is searchable), or upload a `.ttf` / `.otf` / `.ttc` file. *Default (built-in)* is a font that ships with Pillow, so it works everywhere.
  - **Color**: any color. The default is mid-grey because it shows up on both light and dark backgrounds.
- **Image**: upload a logo or other picture. A PNG with a transparent background gives the cleanest result.
  - **Make white background transparent**: for logos saved as JPG on white. Near-white pixels fade out smoothly, so you don't get a hard white box or a jagged halo.

**Appearance**
- **Size**: the watermark's width as a percentage of the page/image width. Because it's relative, the same settings look the same on a small photo and a large scan.
- **Opacity**: 0% is invisible and 100% is fully solid. 25–45% is typical for a watermark.

**Layout**
- **Single**: one watermark.
  - **Position**: any of the 9 anchor points (corners, edges, centre).
  - **Edge margin**: the gap from the edge, as a % of the shorter side.
- **Repeated (tiled)**: a repeating pattern across the whole page.
  - **Horizontal / vertical gap**: the space between copies.
  - **Stagger rows**: offsets every other row by half a tile, giving a brick pattern.
- **Rotation**: −180° to 180°, counter-clockwise. In tiled mode it defaults to 30° for the classic slanted watermark.

### Output options (main area, "Output options")
- **Image output format**: keep the input's format, or convert. JPEG and BMP have no transparency, so the result is flattened onto white.
- **JPEG / WEBP quality**: compression quality.
- **Flatten PDF pages to images**: turns every page into an image (150 DPI) after watermarking. The watermark becomes part of the page and can't simply be deleted in a PDF editor. The downside is that text is no longer selectable or searchable, and files are usually larger.

---

## How it works

```
app.py                     Streamlit UI: sidebar settings, upload, preview, downloads
watermarker/
├── core.py                Renders the watermark and composites it onto an image
├── documents.py           File handling: images, PDFs, text/DOCX → PDF conversion
└── fonts.py               Finds fonts installed on the system
```

### 1. Rendering the watermark (`watermarker/core.py`)

All the settings live in one `WatermarkSettings` dataclass. Rendering has three steps:

1. **`render_mark()`** draws one copy of the watermark at full opacity, with no rotation.
   - *Text*: the text is first measured at a reference font size. The font size is then scaled so the text block's width matches the **Size** setting. That's why size is a percentage, not a point size.
   - *Image*: the logo is resized to the target width, keeping its aspect ratio.
2. **`build_layer()`** places that mark on a transparent layer the same size as the target:
   - **Single**: the mark is rotated (the canvas expands so corners aren't clipped), then pasted at the chosen anchor and margin.
   - **Tiled**: the marks are laid out in an *unrotated* grid on a square canvas whose side equals the target's diagonal. That **whole grid** is then rotated and the centre is cropped out. This gives evenly spaced diagonal rows with no gaps at the corners, which rotating each tile separately would not.
   - Finally, the layer's alpha channel is scaled by **Opacity**.
3. **`watermark_image()`** alpha-composites the layer over the image.

### 2. File types (`watermarker/documents.py`)

- **Images** are opened with Pillow, watermarked, and saved in the chosen format. Animated GIF/WEBP files use their first frame.
- **PDFs** are handled with PyMuPDF. For each page, a watermark layer is rendered at 2× the page's point size (≈144 DPI) and inserted as a transparent image **on top of** the page. The original text and vector graphics stay as they are (still selectable and searchable). Pages with the same size reuse one embedded image, so file size stays small. Rotated pages (90°/180°/270°) are handled so the watermark appears upright as you view the page.
- **Text files** are escaped into HTML and laid out across A4 pages with PyMuPDF's `Story` engine. The resulting PDF is then watermarked like any other PDF.
- **DOCX files** are read with `python-docx`. Headings, paragraphs, **bold**/*italic*/underline and tables become HTML, then go through the same PDF path. Embedded images and complex layout (columns, text boxes, headers/footers) aren't reproduced. For an exact copy of a Word document, export it to PDF from Word first and upload the PDF.

### 3. The UI (`app.py`)

- The **preview** uses a downscaled copy of the file (max 1400 px), and for documents only the selected page. That keeps the sliders responsive. Converted PDFs and preview bases are cached with `st.cache_data`.
- **Downloads are deferred**: the full-resolution watermarking runs only when you click a download button. Streamlit `download_button` accepts a callable for this, so moving a slider never re-processes large files.

### Using the engine without the UI

```python
from PIL import Image
from watermarker import WatermarkSettings, watermark_image
from watermarker import documents

s = WatermarkSettings(text="DRAFT", mode="tiled", rotation=30, size=25, opacity=30)

# Image
watermark_image(Image.open("photo.jpg"), s).convert("RGB").save("photo_wm.jpg")

# PDF / DOCX / TXT
pdf = documents.to_pdf("report.docx", open("report.docx", "rb").read())
open("report_wm.pdf", "wb").write(documents.watermark_pdf(pdf, s))
```

---

## Deploying to Streamlit Community Cloud

1. Push this repo to GitHub (already done if you're reading this there).
2. Go to [share.streamlit.io](https://share.streamlit.io), click **New app**, select this repo and set the main file to `app.py`.
3. Server machines have few fonts installed. Users can still use *Default (built-in)* or upload their own font file.

## Limitations

- Watermarks on image files are part of the pixels and can't be removed. PDF watermarks are a separate layer unless you choose **Flatten**.
- DOCX conversion keeps text structure only (see above).
- Very large images (e.g. > 50 MP) can take a few seconds to process at full resolution.

## Tech stack

[Streamlit](https://streamlit.io) · [Pillow](https://python-pillow.org) · [PyMuPDF](https://pymupdf.readthedocs.io) · [python-docx](https://python-docx.readthedocs.io)
