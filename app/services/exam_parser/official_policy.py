import re
from typing import Literal


FIXED_CATEGORY_BY_NUMBER: dict[int, str] = {
    18: "목적 추론",
    19: "심경,분위기",
    20: "요지,주장",
    21: "함축 의미 추론",
    22: "요지,주장",
    23: "주제 추론",
    24: "제목 추론",
    25: "도표 이해",
    26: "내용 일치,불일치",
    27: "내용 일치,불일치",
    28: "내용 일치,불일치",
    29: "어법",
    30: "어휘 추론",
    31: "빈칸 추론",
    32: "빈칸 추론",
    33: "빈칸 추론",
    34: "빈칸 추론",
    35: "무관한 문장",
    36: "글의 순서",
    37: "글의 순서",
    38: "문장 삽입",
    39: "문장 삽입",
    40: "요약문 완성",
    41: "제목 추론",
    42: "어휘 추론",
    43: "글의 순서",
    44: "지칭 추론",
    45: "내용 일치,불일치",
}

LISTENING_INSTRUCTION_PATTERN = re.compile(r"다음을\s*듣고|대화를\s*듣고")


def _safe_number(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def evaluate_official_exam(questions: list[dict], pdf_page_count: int | None = None) -> dict:
    numbers = sorted(n for n in (_safe_number(q.get("number")) for q in questions) if n is not None)

    unique = list(dict.fromkeys(numbers))
    in_range = [n for n in unique if 18 <= n <= 45]
    out_of_range = [n for n in unique if n < 18 or n > 45]

    checks: list[dict] = []

    if isinstance(pdf_page_count, int):
        hard_page_check = {
            "id": "hard-page-8",
            "label": "PDF 페이지 수 8페이지",
            "passed": pdf_page_count == 8,
            "score": 1 if pdf_page_count == 8 else 0,
            "maxScore": 1,
            "detail": f"감지 페이지: {pdf_page_count}",
        }
    else:
        hard_page_check = {
            "id": "hard-page-8",
            "label": "PDF 페이지 수 8페이지",
            "passed": False,
            "score": 0,
            "maxScore": 1,
            "detail": "PDF 페이지 정보를 사용할 수 없음",
        }
    checks.append(hard_page_check)

    has_only_18_to_45 = len(out_of_range) == 0
    checks.append(
        {
            "id": "hard-range-18-45",
            "label": "문항 번호 범위 18~45",
            "passed": has_only_18_to_45,
            "score": 1 if has_only_18_to_45 else 0,
            "maxScore": 1,
            "detail": f"범위 밖 문항: {', '.join(map(str, out_of_range))}" if out_of_range else "정상",
        }
    )

    hard_min_questions = len(in_range) >= 24
    checks.append(
        {
            "id": "hard-min-questions",
            "label": "최소 문항 수(24개 이상)",
            "passed": hard_min_questions,
            "score": 1 if hard_min_questions else 0,
            "maxScore": 1,
            "detail": f"감지 문항: {len(in_range)}",
        }
    )

    question_by_number: dict[int, dict] = {}
    for q in questions:
        n = _safe_number(q.get("number"))
        if n is not None and n not in question_by_number:
            question_by_number[n] = q

    mismatches: list[str] = []
    for n in range(18, 46):
        expected = FIXED_CATEGORY_BY_NUMBER[n]
        category = question_by_number.get(n, {}).get("category")
        actual = str((category or {}).get("name") or "").strip()
        if not actual:
            mismatches.append(f"Q{n}:missing")
            continue
        if actual != expected:
            mismatches.append(f"Q{n}:{actual}->{expected}")

    fixed_slot_match_rate = 1 - (len(mismatches) / 28)
    fixed_slot_match_rate = max(0.0, fixed_slot_match_rate)
    checks.append(
        {
            "id": "soft-fixed-slot-categories",
            "label": "번호별 문제유형 패턴 일치율(사실상 고정)",
            "passed": fixed_slot_match_rate >= 0.75,
            "score": round(fixed_slot_match_rate * 20),
            "maxScore": 20,
            "detail": f"{round(fixed_slot_match_rate * 100)}% ({len(mismatches)}개 불일치)",
        }
    )

    coverage = len([n for n in in_range if 18 <= n <= 45]) / 28
    checks.append(
        {
            "id": "soft-coverage",
            "label": "18~45 커버리지",
            "passed": coverage >= 0.9,
            "score": round(coverage * 20),
            "maxScore": 20,
            "detail": f"{round(coverage * 100)}%",
        }
    )

    has_41_to_45 = all(n in in_range for n in (41, 42, 43, 44, 45))
    checks.append(
        {
            "id": "soft-last-five",
            "label": "후반 41~45 존재",
            "passed": has_41_to_45,
            "score": 15 if has_41_to_45 else 0,
            "maxScore": 15,
        }
    )

    has_43_to_45 = all(n in in_range for n in (43, 44, 45))
    checks.append(
        {
            "id": "soft-long-reading",
            "label": "장문 핵심 43~45 존재",
            "passed": has_43_to_45,
            "score": 15 if has_43_to_45 else 0,
            "maxScore": 15,
        }
    )

    if not questions:
        choices5_ratio = 0.0
    else:
        choices5_ratio = len(
            [q for q in questions if isinstance((q.get("content") or {}).get("choices"), list) and len((q.get("content") or {}).get("choices")) == 5]
        ) / len(questions)

    checks.append(
        {
            "id": "soft-choices-5",
            "label": "선택지 5개 유지율",
            "passed": choices5_ratio >= 0.9,
            "score": round(choices5_ratio * 25),
            "maxScore": 25,
            "detail": f"{round(choices5_ratio * 100)}%",
        }
    )

    no_listening = True
    for q in questions:
        instruction = str(((q.get("content") or {}).get("instruction") or ""))
        if LISTENING_INSTRUCTION_PATTERN.search(instruction):
            no_listening = False
            break
    checks.append(
        {
            "id": "soft-no-listening",
            "label": "결과 JSON에 듣기 문항 미포함",
            "passed": no_listening,
            "score": 25 if no_listening else 0,
            "maxScore": 25,
            "detail": "원본 시험지에 듣기(1~17)가 있어도, 출력 대상은 18~45만 유지됨"
            if no_listening
            else "결과에 듣기 발문이 포함됨(제외 필요)",
        }
    )

    hard_passed = all(c["passed"] for c in checks if str(c["id"]).startswith("hard-"))
    scored = [c for c in checks if str(c["id"]).startswith("soft-")]
    official_score = sum(int(c["score"]) for c in scored)
    max_score = sum(int(c["maxScore"]) for c in scored)

    verdict: Literal["official", "review", "user"] = "user"
    if hard_passed and official_score >= 75:
        verdict = "official"
    elif hard_passed and official_score >= 60:
        verdict = "review"

    return {
        "hardPassed": hard_passed,
        "officialScore": official_score,
        "maxScore": max_score,
        "verdict": verdict,
        "checks": checks,
    }