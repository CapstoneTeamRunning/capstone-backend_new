from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class PdfPageImage:
    image_bytes: bytes
    file_name: str


def convert_pdf_to_images(pdf_bytes: bytes, original_file_name: str) -> list[PdfPageImage]:
    if not pdf_bytes:
        raise ValueError("empty pdf data")

    stem = Path(original_file_name).stem or "document"

    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"failed to open pdf: {exc}") from exc

    page_images: list[PdfPageImage] = []
    try:
        for idx, page in enumerate(document, start=1):
            # 2.0 zoom yields readable text while keeping payload size moderate.
            matrix = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image_bytes = pix.tobytes("png")
            page_images.append(PdfPageImage(image_bytes=image_bytes, file_name=f"{stem}_p{idx}.png"))
    finally:
        document.close()

    if not page_images:
        raise ValueError("pdf has no pages")

    return page_images
