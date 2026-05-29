import json
import os
from ast import literal_eval
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import OcrResult
from app.services.user_stats import increment_total_generated_count
from question_generation_bridge.modal_client import ModalQuestionClient
from question_generation_bridge.question_generation import create_question_generation_router


def fetch_latest_ocr_result_for_question_generation(document_id: int) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        ocr_result = db.scalar(
            select(OcrResult)
            .where(OcrResult.document_id == document_id, OcrResult.is_latest.is_(True))
            .order_by(OcrResult.created_at.desc())
        )
        if ocr_result is None:
            return None
        return {
            "id": ocr_result.id,
            "ocr_result_id": ocr_result.id,
            "ocr_data": ocr_result.ocr_data,
        }
    finally:
        db.close()


def _json_dump(value: Any, fallback: Any) -> str:
    return json.dumps(value if value is not None else fallback, ensure_ascii=False)


def _time_ago_text(value: datetime | None) -> str:
    if value is None:
        return ""
    now = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    seconds = max(int((now - value).total_seconds()), 0)
    if seconds < 60:
        return "방금 전"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}분 전"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}시간 전"
    days = hours // 24
    if days < 30:
        return f"{days}일 전"
    months = days // 30
    if months < 12:
        return f"{months}개월 전"
    return f"{months // 12}년 전"


def _choice_dto(value: Any, fallback_index: int) -> dict[str, Any]:
    parsed = value
    if isinstance(value, str):
        try:
            parsed = literal_eval(value)
        except (ValueError, SyntaxError):
            parsed = {"text": value}
    if isinstance(parsed, dict):
        return {
            "index": parsed.get("index") or fallback_index,
            "text": str(parsed.get("text") or ""),
        }
    return {"index": fallback_index, "text": str(parsed or "")}


def _choices_dto(raw_choices: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_choices, list):
        return []
    return [
        choice
        for index, raw_choice in enumerate(raw_choices, start=1)
        if (choice := _choice_dto(raw_choice, index)).get("text")
    ]


def _generated_question_dto(row: dict[str, Any]) -> dict[str, Any]:
    created_at = row.get("created_at")
    return {
        "question_id": row.get("question_id"),
        "document_id": row.get("document_id"),
        "ocr_result_id": row.get("ocr_result_id"),
        "question_no": row.get("question_no"),
        "type": row.get("type") or "",
        "instruction": row.get("instruction") or "",
        "passage": row.get("passage") or "",
        "choices": _choices_dto(row.get("choices")),
        "answer": row.get("answer"),
        "explanation": row.get("explanation") or "",
        "difficulty": row.get("difficulty"),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else "",
        "time_ago": _time_ago_text(created_at if isinstance(created_at, datetime) else None),
    }


def insert_generated_question_from_modal(payload: dict[str, Any]) -> dict[str, Any]:
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                INSERT INTO questions
                (
                    ocr_result_id, question_no, type, body_data, choices, answer,
                    explanation, source_type, source_question_id, created_at,
                    exam_code, category_code, category_name, instruction, passage,
                    correct_rate, raw_json, external_code, module
                )
                VALUES
                (
                    :ocr_result_id, :question_no, :type, CAST(:body_data AS jsonb),
                    CAST(:choices AS jsonb), :answer, :explanation,
                    CAST(:source_type AS question_source_type), :source_question_id,
                    now(), :exam_code, :category_code, :category_name,
                    :instruction, :passage, :correct_rate, CAST(:raw_json AS jsonb),
                    :external_code, CAST(:module AS module_type)
                )
                RETURNING id
                """
            ),
            {
                **payload,
                "body_data": _json_dump(payload.get("body_data"), {}),
                "choices": _json_dump(payload.get("choices"), []),
                "raw_json": _json_dump(payload.get("raw_json"), {}),
            },
        ).mappings().first()
        user_row = db.execute(
            text(
                """
                SELECT d.user_id
                FROM ocr_results o
                JOIN documents d ON d.id = o.document_id
                WHERE o.id = :ocr_result_id
                LIMIT 1
                """
            ),
            {"ocr_result_id": payload.get("ocr_result_id")},
        ).mappings().first()
        if user_row is not None:
            increment_total_generated_count(db, int(user_row["user_id"]))
        db.commit()
        return dict(row) if row is not None else {}
    finally:
        db.close()


modal_question_client = ModalQuestionClient(
    os.getenv(
        "MODAL_QUESTION_API_URL",
        "https://kcy021012--ultra-tuning-question-api-vllm-server-question-api.modal.run",
    ),
    timeout_seconds=int(os.getenv("MODAL_QUESTION_TIMEOUT_SECONDS", "110")),
)

router = APIRouter()
router.include_router(create_question_generation_router(
    fetch_latest_ocr_result=fetch_latest_ocr_result_for_question_generation,
    insert_question=insert_generated_question_from_modal,
    modal_client=modal_question_client,
))


@router.get("/questions/generated", response_model=list[dict])
def get_generated_questions(
    user_id: int = Query(...),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT
                q.id AS question_id,
                d.id AS document_id,
                q.ocr_result_id,
                q.question_no,
                q.type,
                q.instruction,
                q.passage,
                q.choices,
                q.answer,
                q.explanation,
                NULLIF(q.raw_json #>> '{requested,difficulty}', '')::int AS difficulty,
                q.created_at
            FROM questions q
            JOIN ocr_results o ON o.id = q.ocr_result_id
            JOIN documents d ON d.id = o.document_id
            WHERE d.user_id = :user_id
              AND q.source_type = 'generated'
            ORDER BY q.created_at DESC, q.id DESC
            """
        ),
        {"user_id": user_id},
    ).mappings().all()
    return [_generated_question_dto(dict(row)) for row in rows]


@router.delete("/questions/generated/{question_id}", status_code=204)
def delete_generated_question(
    question_id: int,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
) -> Response:
    row = db.execute(
        text(
            """
            DELETE FROM questions q
            USING ocr_results o, documents d
            WHERE q.id = :question_id
              AND q.ocr_result_id = o.id
              AND o.document_id = d.id
              AND d.user_id = :user_id
              AND q.source_type = 'generated'
            RETURNING q.id
            """
        ),
        {"question_id": question_id, "user_id": user_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Generated question not found")
    db.commit()
    return Response(status_code=204)
