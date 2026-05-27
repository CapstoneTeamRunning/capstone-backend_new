import json
import os
from typing import Any

from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import OcrResult
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
        db.commit()
        return dict(row) if row is not None else {}
    finally:
        db.close()


modal_question_client = ModalQuestionClient(
    os.getenv(
        "MODAL_QUESTION_API_URL",
        "https://kcy021012--ultra-tuning-question-api-vllm-server-question-api.modal.run",
    )
)

router = create_question_generation_router(
    fetch_latest_ocr_result=fetch_latest_ocr_result_for_question_generation,
    insert_question=insert_generated_question_from_modal,
    modal_client=modal_question_client,
)
