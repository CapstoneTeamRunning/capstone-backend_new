import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/exam-sets", tags=["exam-sets"])

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "exam_question.json"
EXAM_CODE_PATTERN = re.compile(r"^(?P<year>\d{4})-(?P<month>06M|09M)-(?P<number>\d+)$")


@lru_cache(maxsize=1)
def _load_questions() -> list[dict[str, Any]]:
    with DATA_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise RuntimeError("exam_question.json must contain a JSON array")
    return [item for item in data if isinstance(item, dict)]


def _exam_code(item: dict[str, Any]) -> str | None:
    code = str(item.get("code") or "")
    match = EXAM_CODE_PATTERN.match(code)
    if match is None:
        return None
    return f"{match.group('year')}-{match.group('month')}"


def _is_chart_question(item: dict[str, Any]) -> bool:
    category = item.get("category")
    if not isinstance(category, dict):
        return False
    return "도표" in str(category.get("name") or "")


def _has_valid_passage(item: dict[str, Any]) -> bool:
    content = item.get("content")
    if not isinstance(content, dict):
        return False

    passage = str(content.get("passage") or "").strip()
    normalized_passage = re.sub(r"\[[^\]]*\]", " ", passage)
    normalized_passage = re.sub(r"\s+", " ", normalized_passage).strip()
    invalid_markers = ("[not parsed]", "들려주는 지문 내용", "지문 내용 없음")

    return len(normalized_passage) >= 120 and not any(
        marker in passage.lower() for marker in invalid_markers
    )


def _is_visible_question(item: dict[str, Any]) -> bool:
    return not _is_chart_question(item) and _has_valid_passage(item)


def _exam_title(exam_code: str) -> str:
    year, month_code = exam_code.split("-", 1)
    month = "6월" if month_code == "06M" else "9월"
    return f"{year}학년도 {month} 모의고사"


def _exam_subtitle(exam_code: str) -> str:
    year, month_code = exam_code.split("-", 1)
    month = "6월" if month_code == "06M" else "9월"
    return f"{int(year) - 1}년 {month} 시행 평가원 모의평가"


def _exam_sort_key(exam_code: str) -> tuple[int, int]:
    year, month_code = exam_code.split("-", 1)
    month = 6 if month_code == "06M" else 9
    return int(year), month


@router.get("", response_model=list[dict])
def get_exam_sets() -> list[dict[str, Any]]:
    grouped: dict[str, int] = {}
    for item in _load_questions():
        if not _is_visible_question(item):
            continue
        exam_code = _exam_code(item)
        if exam_code is not None:
            grouped[exam_code] = grouped.get(exam_code, 0) + 1

    return [
        {
            "exam_code": exam_code,
            "title": _exam_title(exam_code),
            "grade_month": _exam_subtitle(exam_code),
            "description": f"18~45번 {count}문항",
            "question_count": count,
        }
        for exam_code, count in sorted(grouped.items(), key=lambda item: _exam_sort_key(item[0]), reverse=True)
    ]


@router.get("/{exam_code}/questions", response_model=list[dict])
def get_exam_questions(exam_code: str) -> list[dict[str, Any]]:
    if not re.match(r"^\d{4}-(06M|09M)$", exam_code):
        raise HTTPException(status_code=404, detail="exam set not found")

    prefix = f"{exam_code}-"
    questions = [
        item
        for item in _load_questions()
        if isinstance(item.get("code"), str)
        and item["code"].startswith(prefix)
        and _is_visible_question(item)
    ]
    if not questions:
        raise HTTPException(status_code=404, detail="exam set not found")

    return sorted(questions, key=lambda item: int(item.get("number") or 0))
