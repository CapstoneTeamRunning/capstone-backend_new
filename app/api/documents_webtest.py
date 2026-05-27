import json
import random
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
from app.models import AnalysisResult, AnalysisRun, Document, OcrResult, User
from app.schemas import (
    DocumentOcrMockResponse,
    DocumentParseMockResponse,
    DocumentParseStatusResponse,
    DocumentUploadListResponse,
    DocumentUploadResponse,
)
from app.services.pdf_converter_service import convert_pdf_to_images

try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
except ImportError:
    BlobServiceClient = None
    ContentSettings = None

router = APIRouter(prefix="/documents", tags=["documents"])

BASE_DIR = Path(__file__).resolve().parents[2]
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024
TEST_JSON_PATH = BASE_DIR / "test.json"
_cached_mock_questions: list[dict] | None = None


class AnalyzeRequest(BaseModel):
    text: str
    passage_code: str = "TEMP"
    topic_title: str = "임시 주제"
    api_key: str | None = None
    provider: str | None = None
    model: str | None = None


def _parse_json_object(raw: str) -> dict:
    text_raw = raw.strip()
    if text_raw.startswith("```"):
        text_raw = re.sub(r"^```[a-zA-Z]*\s*", "", text_raw)
        text_raw = re.sub(r"\s*```$", "", text_raw).strip()
    start = text_raw.find("{")
    end = text_raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("AI 응답에서 JSON 객체를 찾지 못했습니다.")
    parsed = json.loads(text_raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("AI 응답 JSON 최상위 타입이 object가 아닙니다.")
    return parsed


def _build_parse_overlay_prompt(*, code: str, topic: str, full_text: str) -> str:
    return f"""You are a world-class English syntax analysis and translation expert AI.
Your task is to analyze the provided English passage and return a structured JSON object.
Adhere strictly to the JSON format and analysis rules provided below.

### Analysis Rules:
1.  **Overall Structure**: The root object must contain `code`, `topic`, `commentary`, `analysis_data`, and `vocabulary`.
2.  **`topic`**: Read the passage and extract the core topic. You MUST format it exactly as "한글 주제 / English Topic".
3.  **`commentary`**: Provide a one-sentence summary of the entire passage's core message IN KOREAN.
4.  **`sentences`**: Split the passage into individual sentences. For each sentence:
    -   **CRITICAL RULE FOR SPLITTING**: Split the passage into individual sentences strictly based on terminal punctuation (periods `.`, question marks `?`, exclamation marks `!`). NEVER combine two distinct sentences into one.
    -   Assign a sequential `sentence_no`.
    -   Provide a natural, full Korean translation in `full_translation`.
    -   **`is_topic_sentence`**: Always set this value to `false` for now.
    -   Break the entire sentence down into meaningful `chunks`.
5.  **`chunks`**: For each chunk:
    -   **CRITICAL RULE FOR COMPLETENESS**: You MUST analyze every single word of the sentence from the beginning to the very end. DO NOT skip, summarize, or leave out any words, even if the sentence is extremely long.
    -   **CRITICAL RULE FOR CLAUSES**: NEVER group an entire clause (Noun, Adjective, or Adverbial clause) into a single chunk. You MUST split the clause into separate chunks so that its internal Subject (S) and Verb (V) have their own independent chunks.
    -   `chunk_id`: A unique integer index starting from 0 for each chunk in the sentence.
    -   `target_text`: The original English text of the chunk.
    -   `korean_meaning`: A direct, literal Korean translation of the chunk.
    -   `syntax_tag`: Assign one of the following tags: S (Subject), V (Verb), O (Object), C (Complement), M (Modifier).
    -   `box_color`:
        -   Use "red" for the main Subject (S).
        -   Use "blue" for the main Verb (V).
        -   Use "green" for the main Object (O) or Complement (C).
        -   Leave as null for Modifiers (M).
    -   `bracket_open` / `bracket_close`:
        -   Assign `[` to the first chunk of the clause (e.g., the conjunction or relative pronoun).
        -   Assign `]` to the very last chunk of the clause.
        -   DO NOT use brackets for simple phrases or other modifiers.
        -   If multiple clauses end simultaneously, use an array of strings like `["]", "]"]`.
    -   `grammar_note`: If there's a specific grammatical point worth noting, add a brief explanation IN KOREAN ONLY using Korean grammatical terms (e.g., '과거분사', '관계대명사', '부사절'). Do not use English terms like 'Adverbial Clause'.
    -   `modifies_chunk_id`: **STRICTLY** set this to an integer `chunk_id` **ONLY** when the current chunk is an adjective or adjective phrase (`M` tag) that directly modifies a preceding noun or noun phrase. For all other cases (adverbial modifiers, etc.), set it to `null`.
6.  **`vocabulary`**: Extract 3-5 key vocabulary words from the passage and provide their `word` and `meaning` IN KOREAN.
7.  **JSON Formatting Constraints**: Output MUST be perfectly valid JSON.
    - **Escape double quotes** inside string values using backslashes (e.g., \\"word\\"). NEVER use single quotes (') to enclose strings, as it violates JSON standards.
    - **CRITICAL**: You MUST include commas `,` between all elements in arrays (especially between `chunk` objects and `sentence` objects).
    - Do NOT leave trailing commas at the end of arrays or objects.

### Input Data:
-   Passage Code: `{code}`
-   Topic: `{topic}`
-   Passage Text: `{full_text}`

### Output JSON Format (Strictly follow this schema):
{{
  "code": "string",
  "topic": "한글 주제 / English Topic",
  "commentary": "string",
  "analysis_data": {{
    "sentences": [
      {{
        "sentence_no": 1,
        "full_translation": "string",
        "is_topic_sentence": false,
        "chunks": [ ... ]
      }}
    ]
  }},
  "vocabulary": [ {{ "word": "example", "meaning": "예시" }} ]
}}

Now, analyze the provided input data and generate the JSON output.
""".strip()


def _validate_overlay_result(parsed: dict) -> dict:
    analysis_data = parsed.get("analysis_data")
    if not isinstance(analysis_data, dict) or not isinstance(analysis_data.get("sentences"), list):
        raise RuntimeError("AI 응답에 analysis_data.sentences가 없습니다.")
    return parsed


def _call_gemini_parse_overlay(*, code: str, topic: str, full_text: str, api_key: str | None = None, model: str | None = None) -> dict:
    actual_api_key = (api_key or settings.gemini_api_key or "").strip()
    actual_model = (model or settings.ai_model or "gemini-1.5-flash").strip()

    if not actual_api_key:
        raise RuntimeError("GEMINI_API_KEY가 비어 있습니다.")

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("google-genai 패키지가 설치되지 않았습니다.") from exc

    prompt = _build_parse_overlay_prompt(code=code, topic=topic, full_text=full_text)
    try:
        client = genai.Client(
            api_key=actual_api_key,
            http_options=types.HttpOptions(timeout=120000),
        )
        response = client.models.generate_content(
            model=actual_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:
        raise RuntimeError(f"Gemini 호출 실패: {exc}") from exc

    content = getattr(response, "text", None)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Gemini 응답 본문이 비어 있습니다.")
    parsed = _parse_json_object(content)
    return _validate_overlay_result(parsed)


def _call_openrouter_parse_overlay(*, code: str, topic: str, full_text: str, api_key: str | None = None, model: str | None = None) -> dict:
    actual_api_key = (api_key or settings.openrouter_api_key or "").strip()
    actual_model = (model or settings.ai_model or "google/gemini-flash-1.5").strip()

    if not actual_api_key:
        raise RuntimeError("OPENROUTER_API_KEY가 비어 있습니다.")

    prompt = _build_parse_overlay_prompt(code=code, topic=topic, full_text=full_text)
    payload = {
        "model": actual_model,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        url="https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {actual_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Capstone Parse API",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else str(exc)
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter 연결 실패: {exc.reason}") from exc

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("OpenRouter 응답 구조가 예상과 다릅니다.") from exc

    parsed = _parse_json_object(content)
    return _validate_overlay_result(parsed)


def _call_parse_overlay(*, code: str, topic: str, full_text: str, api_key: str | None = None, provider: str | None = None, model: str | None = None) -> dict:
    actual_provider = (provider or settings.ai_provider or "gemini").strip().lower()
    if actual_provider == "gemini":
        return _call_gemini_parse_overlay(code=code, topic=topic, full_text=full_text, api_key=api_key, model=model)
    if actual_provider == "openrouter":
        return _call_openrouter_parse_overlay(code=code, topic=topic, full_text=full_text, api_key=api_key, model=model)
    raise RuntimeError(f"지원하지 않는 AI_PROVIDER입니다: {actual_provider}")


def _upload_to_azure_blob(data: bytes, suffix: str, mime_type: str) -> tuple[str, str]:
    if not BlobServiceClient or not settings.azure_blob_connection_string.strip():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="azure blob connection string is not configured",
        )

    blob_name = f"documents/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{uuid4().hex}{suffix}"
    try:
        blob_service_client = BlobServiceClient.from_connection_string(settings.azure_blob_connection_string)
        container_client = blob_service_client.get_container_client(settings.azure_blob_container)
        container_client.create_container()
    except Exception:
        # 이미 컨테이너가 있거나 권한상 생성 불가해도 업로드는 시도 가능
        container_client = blob_service_client.get_container_client(settings.azure_blob_container)

    try:
        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=mime_type),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed to upload blob: {exc}",
        ) from exc

    blob_url = blob_client.url
    return blob_name, blob_url


def _load_ocr_json_fixture_questions() -> list[dict]:
    global _cached_mock_questions
    if _cached_mock_questions is not None:
        return _cached_mock_questions
    try:
        raw = TEST_JSON_PATH.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="failed to load mock data") from exc
    if not isinstance(parsed, list) or not parsed:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="mock data is empty")
    _cached_mock_questions = parsed
    return parsed


def _run_parse_job(analysis_run_id: int) -> None:
    db = SessionLocal()
    try:
        run = db.scalar(select(AnalysisRun).where(AnalysisRun.id == analysis_run_id))
        if run is None:
            return

        print(f"[parse] request started document_id={run.document_id}")
        db.execute(
            text(
                "UPDATE analysis_runs SET status = CAST(:status AS analysis_status), started_at = :started_at, error_message = NULL WHERE id = :run_id"
            ),
            {"status": "running", "started_at": datetime.now(timezone.utc), "run_id": analysis_run_id},
        )
        db.commit()

        ocr_result = db.scalar(
            select(OcrResult)
            .where(OcrResult.id == run.ocr_result_id)
            .order_by(OcrResult.id.desc())
        )
        if ocr_result is None:
            raise RuntimeError("ocr result not found")

        mock_item = ocr_result.ocr_data if isinstance(ocr_result.ocr_data, dict) else {}
        content = mock_item.get("content", {}) if isinstance(mock_item.get("content", {}), dict) else {}
        full_text = str(content.get("passage", ocr_result.full_content or "")).strip()
        instruction = str(content.get("instruction", "")).strip()
        summary = instruction or "구문 분석 결과"
        code = str(mock_item.get("code", f"DOC-{run.document_id}"))
        topic = str((mock_item.get("category") or {}).get("name", "주제 없음"))

        print(f"[parse] calling provider={settings.ai_provider} model={settings.ai_model} document_id={run.document_id}")
        result_json = _call_parse_overlay(
            code=code,
            topic=topic,
            full_text=full_text
        )
        print(f"[parse] provider call succeeded document_id={run.document_id}")

        existing_result = db.scalar(
            select(AnalysisResult).where(AnalysisResult.analysis_run_id == analysis_run_id)
        )
        if existing_result is None:
            db.add(
                AnalysisResult(
                    analysis_run_id=analysis_run_id,
                    result_json=result_json,
                    summary_text=summary,
                )
            )
        else:
            existing_result.result_json = result_json
            existing_result.summary_text = summary

        db.execute(
            text(
                "UPDATE analysis_runs SET status = CAST(:status AS analysis_status), error_message = NULL, finished_at = :finished_at WHERE id = :run_id"
            ),
            {"status": "succeeded", "finished_at": datetime.now(timezone.utc), "run_id": analysis_run_id},
        )
        db.commit()
    except Exception as exc:
        err = str(exc)
        print(f"[parse] provider call failed document_id={run.document_id if 'run' in locals() and run is not None else 'unknown'}: {err}")
        db.execute(
            text(
                "UPDATE analysis_runs SET status = CAST(:status AS analysis_status), error_message = :error_message, finished_at = :finished_at WHERE id = :run_id"
            ),
            {"status": "failed", "error_message": err, "finished_at": datetime.now(timezone.utc), "run_id": analysis_run_id},
        )
        db.commit()
    finally:
        db.close()


@router.post("/upload", response_model=DocumentUploadListResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    image: UploadFile = File(...),
    user_id: int = Form(1),
    db: Session = Depends(get_db),
) -> DocumentUploadListResponse:
    suffix = Path(image.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported file extension")

    mime_type = image.content_type or ""
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported content type")

    data = await image.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file too large")

    # 프로토타입용 기본 사용자 보정
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        user = User(
            id=user_id,
            username=f"tester-{user_id}",
            email=f"test{user_id}@local.dev",
            password_hash="prototype",
        )
        db.add(user)
        db.flush()

    created_documents: list[DocumentUploadResponse] = []
    is_pdf = suffix == ".pdf" or mime_type == "application/pdf"

    if is_pdf:
        try:
            page_images = convert_pdf_to_images(data, image.filename or "document.pdf")
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid pdf: {exc}") from exc

        for page in page_images:
            blob_name, blob_url = _upload_to_azure_blob(
                data=page.image_bytes,
                suffix=".png",
                mime_type="image/png",
            )
            document = Document(
                user_id=user_id,
                title=page.file_name or blob_name,
                storage_key=blob_url,
                mime_type="image/png",
                file_size=len(page.image_bytes),  # type: ignore[arg-type]
                checksum=sha256(page.image_bytes).hexdigest(),
            )
            db.add(document)
            db.flush()
            created_documents.append(DocumentUploadResponse(document_id=document.id, image_url=blob_url))
    else:
        blob_name, blob_url = _upload_to_azure_blob(data=data, suffix=suffix, mime_type=mime_type)
        document = Document(
            user_id=user_id,
            title=image.filename or blob_name,
            storage_key=blob_url,
            mime_type=mime_type,
            file_size=len(data),  # type: ignore[arg-type]
            checksum=sha256(data).hexdigest(),
        )
        db.add(document)
        db.flush()
        created_documents.append(DocumentUploadResponse(document_id=document.id, image_url=blob_url))

    db.commit()
    return DocumentUploadListResponse(
        documents=created_documents,
        total_count=len(created_documents),
        file_name=image.filename or "",
    )


@router.post("/{document_id}/ocr", response_model=DocumentOcrMockResponse)
def run_ocr_from_json_fixture(
    document_id: int,
    db: Session = Depends(get_db),
) -> DocumentOcrMockResponse:
    document = db.scalar(select(Document).where(Document.id == document_id))
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")

    mock_questions = _load_ocr_json_fixture_questions()
    mock_item = random.choice(mock_questions)
    full_content = str(mock_item.get("content", {}).get("passage", ""))

    current_latest = db.scalars(
        select(OcrResult).where(
            OcrResult.document_id == document_id,
            OcrResult.is_latest.is_(True),
        )
    ).all()
    for row in current_latest:
        row.is_latest = False

    previous_attempt = db.scalar(
        select(OcrResult.attempt_no)
        .where(OcrResult.document_id == document_id)
        .order_by(OcrResult.attempt_no.desc())
        .limit(1)
    )
    attempt_no = (previous_attempt or 0) + 1
    now = datetime.now(timezone.utc)
    ocr_result = OcrResult(
        document_id=document_id,
        ocr_data=mock_item,
        full_content=full_content,
        engine="mock-json",
        attempt_no=attempt_no,
        is_latest=True,
        finished_at=now,
    )
    db.add(ocr_result)
    db.flush()
    db.execute(
        text("UPDATE ocr_results SET status = CAST(:status AS analysis_status) WHERE id = :ocr_result_id"),
        {"status": "succeeded", "ocr_result_id": ocr_result.id},
    )
    db.execute(
        text("UPDATE documents SET status = CAST(:status AS document_status) WHERE id = :document_id"),
        {"status": "ocr_succeeded", "document_id": document_id},
    )
    db.commit()

    return DocumentOcrMockResponse(
        document_id=document_id,
        status="completed",
        mock_item=mock_item,
    )


@router.post(
    "/{document_id}/parse",
    response_model=DocumentParseMockResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_parse_mock(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> DocumentParseMockResponse:
    document = db.scalar(select(Document).where(Document.id == document_id))
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")

    ocr_result = db.scalar(
        select(OcrResult)
        .where(OcrResult.document_id == document_id, OcrResult.is_latest.is_(True))
        .order_by(OcrResult.id.desc())
    )
    if ocr_result is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ocr result not found")

    run = AnalysisRun(
        document_id=document_id,
        ocr_result_id=ocr_result.id,
        model_name=settings.ai_model,
        model_version=settings.ai_provider,
        prompt_version="react-overlay-v1",
    )
    db.add(run)
    db.flush()
    db.commit()
    background_tasks.add_task(_run_parse_job, run.id)

    return DocumentParseMockResponse(
        document_id=document_id,
        analysis_run_id=run.id,
        status="queued",
    )


@router.get("/{document_id}/parse/{analysis_run_id}", response_model=DocumentParseStatusResponse)
def get_parse_status(
    document_id: int,
    analysis_run_id: int,
    db: Session = Depends(get_db),
) -> DocumentParseStatusResponse:
    run = db.scalar(
        select(AnalysisRun).where(
            AnalysisRun.id == analysis_run_id,
            AnalysisRun.document_id == document_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis run not found")

    analysis_result = db.scalar(
        select(AnalysisResult).where(AnalysisResult.analysis_run_id == analysis_run_id)
    )
    return DocumentParseStatusResponse(
        document_id=document_id,
        analysis_run_id=analysis_run_id,
        status=run.status,
        result_json=analysis_result.result_json if analysis_result is not None else None,
        error_message=run.error_message,
    )


@router.post("/analyze", response_model=dict)
def analyze_passage_directly(req: AnalyzeRequest) -> dict:
    try:
        return _call_parse_overlay(
            code=req.passage_code,
            topic=req.topic_title,
            full_text=req.text,
            api_key=req.api_key,
            provider=req.provider,
            model=req.model,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
