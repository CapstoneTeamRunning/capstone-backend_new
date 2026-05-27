import base64
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.services.exam_parser.service import analyze_exam_header_meta, analyze_exam_image, analyze_syntax_text
from app.services.exam_parser.official_policy import evaluate_official_exam
from app.services.exam_parser.upload_service import (
    ALLOWED_IMAGE_MIME_TYPES,
    MAX_UPLOAD_SIZE,
    PDF_EXTENSION,
    PDF_MIME_TYPE,
    convert_pdf_upload_to_images,
    parse_answer_map,
    validate_image_upload,
)

router = APIRouter(prefix="/parser", tags=["parser"])

ALLOWED_FILE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
LISTENING_INSTRUCTION_PATTERN = re.compile(r"다음을\s*듣고|대화를\s*듣고")


class AnalyzeRequest(BaseModel):
    text: str
    passage_code: str = "TEMP"
    topic_title: str = "임시 주제"
    api_key: str | None = None
    provider: str | None = None
    model: str | None = None


class AnalyzeExamImageRequest(BaseModel):
    image_base64: str
    file_name: str = "unknown"
    parse_mode: str = "official"
    code_prefix: str | None = None
    api_key: str | None = None
    provider: str | None = None
    model: str | None = None


class AnalyzeExamHeaderRequest(BaseModel):
    image_base64: str
    api_key: str | None = None
    provider: str | None = None
    model: str | None = None


class OfficialExamCheck(BaseModel):
    id: str
    label: str
    passed: bool
    score: int
    maxScore: int
    detail: str | None = None


class OfficialExamAssessment(BaseModel):
    hardPassed: bool
    officialScore: int
    maxScore: int
    verdict: Literal["official", "review", "user"]
    checks: list[OfficialExamCheck]


class AnalyzeExamFileResponse(BaseModel):
    items: list[dict]
    source_type: Literal["pdf", "image"]
    page_count: int
    parsed_page_count: int
    assessment: OfficialExamAssessment | None = None


def _to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _to_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _apply_answer_map(items: list[dict], answer_map: dict[int, int]) -> None:
    if not answer_map:
        return
    for item in items:
        num = _to_int(item.get("number"))
        if num is not None and num in answer_map:
            item["answer"] = answer_map[num]


async def _read_answer_map(answer_file: UploadFile | None) -> dict[int, int]:
    if answer_file is None:
        return {}
    answer_bytes = await answer_file.read()
    return parse_answer_map(answer_bytes)


def _parse_exam_image_payload(
    *,
    image_bytes: bytes,
    file_name: str,
    parse_mode: str,
    code_prefix: str | None,
    api_key: str | None,
    provider: str | None,
    model: str | None,
) -> list[dict]:
    items = analyze_exam_image(
        image_base64=_to_base64(image_bytes),
        file_name=file_name,
        parse_mode=parse_mode,
        code_prefix=code_prefix,
        api_key=api_key,
        provider=provider,
        model=model,
    )
    if parse_mode == "official":
        items = _filter_official_questions(items)
    return items


def _filter_official_questions(items: list[dict]) -> list[dict]:
    filtered: list[dict] = []
    for item in items:
        number = _to_int(item.get("number"))
        if number is None or number < 18 or number > 45:
            continue

        content = item.get("content") if isinstance(item.get("content"), dict) else {}
        instruction = str(content.get("instruction") or "")
        if LISTENING_INSTRUCTION_PATTERN.search(instruction):
            continue

        filtered.append(item)

    return filtered


@router.post("/analyze", response_model=dict)
def analyze_passage(req: AnalyzeRequest) -> dict:
    try:
        return analyze_syntax_text(
            text=req.text,
            passage_code=req.passage_code,
            topic_title=req.topic_title,
            api_key=req.api_key,
            provider=req.provider,
            model=req.model,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/exam/analyze-image", response_model=list[dict])
def analyze_exam(req: AnalyzeExamImageRequest) -> list[dict]:
    try:
        if req.parse_mode not in {"official", "user"}:
            raise ValueError("parse_mode는 'official' 또는 'user'만 허용됩니다.")

        result = analyze_exam_image(
            image_base64=req.image_base64,
            file_name=req.file_name,
            parse_mode=req.parse_mode,
            code_prefix=req.code_prefix,
            api_key=req.api_key,
            provider=req.provider,
            model=req.model,
        )
        if req.parse_mode == "official":
            return _filter_official_questions(result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/exam/analyze-file", response_model=AnalyzeExamFileResponse)
async def analyze_exam_file(
    file: UploadFile = File(...),
    answer_file: UploadFile | None = File(None),
    parse_mode: str = Form("official"),
    code_prefix: str | None = Form(None),
    api_key: str | None = Form(None),
    provider: str | None = Form(None),
    model: str | None = Form(None),
) -> AnalyzeExamFileResponse:
    try:
        if parse_mode not in {"official", "user"}:
            raise ValueError("parse_mode는 'official' 또는 'user'만 허용됩니다.")

        answer_map = await _read_answer_map(answer_file)

        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_FILE_EXTENSIONS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported file extension")

        mime_type = file.content_type or ""
        is_pdf = suffix == ".pdf" or mime_type == "application/pdf"
        if not is_pdf and mime_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported content type")

        data = await file.read()
        if not data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")
        if len(data) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file too large")

        if is_pdf:
            page_images = convert_pdf_upload_to_images(
                file_name=file.filename or "document.pdf",
                mime_type=mime_type,
                data=data,
            )
            parsed_items: list[dict] = []
            for page in page_images:
                page_items = _parse_exam_image_payload(
                    image_bytes=page.image_bytes,
                    file_name=page.file_name,
                    parse_mode=parse_mode,
                    code_prefix=code_prefix,
                    api_key=api_key,
                    provider=provider,
                    model=model,
                )
                parsed_items.extend(page_items)

            _apply_answer_map(parsed_items, answer_map)

            assessment = None
            if parse_mode == "official":
                assessment = evaluate_official_exam(parsed_items, pdf_page_count=len(page_images))

            return AnalyzeExamFileResponse(
                items=parsed_items,
                source_type="pdf",
                page_count=len(page_images),
                parsed_page_count=len(page_images),
                assessment=assessment,
            )

        validated = validate_image_upload(
            file_name=file.filename or "unknown",
            mime_type=mime_type,
            data=data,
        )
        result = _parse_exam_image_payload(
            image_bytes=validated.image_bytes,
            file_name=validated.file_name,
            parse_mode=parse_mode,
            code_prefix=code_prefix,
            api_key=api_key,
            provider=provider,
            model=model,
        )

        _apply_answer_map(result, answer_map)

        assessment = None
        if parse_mode == "official":
            assessment = evaluate_official_exam(result, pdf_page_count=None)

        return AnalyzeExamFileResponse(
            items=result,
            source_type="image",
            page_count=1,
            parsed_page_count=1,
            assessment=assessment,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/exam/analyze-upload/image", response_model=AnalyzeExamFileResponse)
async def analyze_exam_uploaded_image(
    file: UploadFile = File(...),
    answer_file: UploadFile | None = File(None),
    parse_mode: str = Form("official"),
    code_prefix: str | None = Form(None),
    api_key: str | None = Form(None),
    provider: str | None = Form(None),
    model: str | None = Form(None),
) -> AnalyzeExamFileResponse:
    try:
        if parse_mode not in {"official", "user"}:
            raise ValueError("parse_mode는 'official' 또는 'user'만 허용됩니다.")

        data = await file.read()
        validated = validate_image_upload(
            file_name=file.filename or "unknown",
            mime_type=file.content_type or "",
            data=data,
        )
        answer_map = await _read_answer_map(answer_file)

        items = _parse_exam_image_payload(
            image_bytes=validated.image_bytes,
            file_name=validated.file_name,
            parse_mode=parse_mode,
            code_prefix=code_prefix,
            api_key=api_key,
            provider=provider,
            model=model,
        )
        _apply_answer_map(items, answer_map)

        assessment = None
        if parse_mode == "official":
            assessment = evaluate_official_exam(items, pdf_page_count=None)

        return AnalyzeExamFileResponse(
            items=items,
            source_type="image",
            page_count=1,
            parsed_page_count=1,
            assessment=assessment,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/exam/analyze-upload/pdf", response_model=AnalyzeExamFileResponse)
async def analyze_exam_uploaded_pdf(
    file: UploadFile = File(...),
    answer_file: UploadFile | None = File(None),
    parse_mode: str = Form("official"),
    code_prefix: str | None = Form(None),
    api_key: str | None = Form(None),
    provider: str | None = Form(None),
    model: str | None = Form(None),
) -> AnalyzeExamFileResponse:
    try:
        if parse_mode not in {"official", "user"}:
            raise ValueError("parse_mode는 'official' 또는 'user'만 허용됩니다.")

        data = await file.read()
        page_images = convert_pdf_upload_to_images(
            file_name=file.filename or "document.pdf",
            mime_type=file.content_type or "",
            data=data,
        )
        answer_map = await _read_answer_map(answer_file)

        parsed_items: list[dict] = []
        for page in page_images:
            page_items = _parse_exam_image_payload(
                image_bytes=page.image_bytes,
                file_name=page.file_name,
                parse_mode=parse_mode,
                code_prefix=code_prefix,
                api_key=api_key,
                provider=provider,
                model=model,
            )
            parsed_items.extend(page_items)

        _apply_answer_map(parsed_items, answer_map)

        assessment = None
        if parse_mode == "official":
            assessment = evaluate_official_exam(parsed_items, pdf_page_count=len(page_images))

        return AnalyzeExamFileResponse(
            items=parsed_items,
            source_type="pdf",
            page_count=len(page_images),
            parsed_page_count=len(page_images),
            assessment=assessment,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/exam/header-meta", response_model=dict | None)
def analyze_exam_header(req: AnalyzeExamHeaderRequest) -> dict | None:
    try:
        return analyze_exam_header_meta(
            image_base64=req.image_base64,
            api_key=req.api_key,
            provider=req.provider,
            model=req.model,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
