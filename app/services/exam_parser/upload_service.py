import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, status

from app.services.pdf_converter_service import PdfPageImage, convert_pdf_to_images

ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PDF_EXTENSION = ".pdf"
PDF_MIME_TYPE = "application/pdf"
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
ANSWER_LINE_PATTERN = re.compile(r"(\d+)\s*:\s*(\d+)")


@dataclass
class UploadedExamImage:
    file_name: str
    image_bytes: bytes


def validate_image_upload(*, file_name: str, mime_type: str, data: bytes) -> UploadedExamImage:
    suffix = Path(file_name).suffix.lower()

    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported image extension")
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported image content type")
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file too large")

    return UploadedExamImage(file_name=file_name, image_bytes=data)


def convert_pdf_upload_to_images(*, file_name: str, mime_type: str, data: bytes) -> list[PdfPageImage]:
    suffix = Path(file_name).suffix.lower()

    if suffix != PDF_EXTENSION and mime_type != PDF_MIME_TYPE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pdf file is required")
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file too large")

    try:
        return convert_pdf_to_images(data, file_name)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid pdf: {exc}") from exc


def parse_answer_map(answer_bytes: bytes) -> dict[int, int]:
    answer_text = answer_bytes.decode("utf-8", errors="ignore")
    answer_map: dict[int, int] = {}
    for line in answer_text.splitlines():
        match = ANSWER_LINE_PATTERN.search(line)
        if match:
            q_num = int(match.group(1))
            ans_num = int(match.group(2))
            answer_map[q_num] = ans_num
    return answer_map
