"""
수능 문제 지문 정제 서비스.

문제 유형별로 지문에서 [본문]/[제시문] 레이블을 제거하고,
빈칸/삽입/순서 등 유형에 맞게 정답을 반영한 완성된 지문을 반환한다.
"""
from __future__ import annotations

import re
from typing import Any

# ────────────────────────────────────────────
# 정규식 상수
# ────────────────────────────────────────────
_BLANK_RE = re.compile(r"_{3,}")                            # _____ (3자 이상)
_SECTION_RE = re.compile(r"\[(본문|제시문|지문)\]")          # [본문] [제시문] [지문]
_CIRCLE_PAREN_RE = re.compile(r"\(\s*([①②③④⑤])\s*\)")    # ( ① )
_CIRCLE_INLINE_RE = re.compile(r"[①②③④⑤]")               # ① 인라인
_ABC_BLOCK_RE = re.compile(r"(?m)^\(([A-Z])\)\s*")         # (A) (B) (C) 블록 시작
_ABC_ORDER_RE = re.compile(r"\(([A-Z])\)")                  # 순서 선택지 "(B) - (A) - (C)"
_WHITESPACE_RE = re.compile(r"[ \t]{2,}")
_NEWLINE_RE = re.compile(r"\n{3,}")

CIRCLE_ORDER = ["①", "②", "③", "④", "⑤"]


# ────────────────────────────────────────────
# 내부 헬퍼
# ────────────────────────────────────────────

def _strip_section_labels(text: str) -> str:
    text = _SECTION_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    text = _NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def _split_intro_body(passage: str) -> tuple[str, str]:
    """[제시문]...[본문]... 구조 분리. intro가 먼저 오는 경우."""
    intro_m = re.search(r"\[제시문\](.*?)(?=\[본문\]|$)", passage, re.DOTALL)
    body_m = re.search(r"\[본문\](.*?)(?=\[제시문\]|$)", passage, re.DOTALL)

    intro = intro_m.group(1).strip() if intro_m else ""
    body = body_m.group(1).strip() if body_m else ""

    if not intro_m and not body_m:
        body = passage.strip()

    return intro, body


def _pick_choice_text(choices: list[Any] | None, answer: int | None) -> str | None:
    """choices 리스트에서 answer 번호(1-based)에 해당하는 텍스트 반환."""
    if not choices or not answer:
        return None
    for c in choices:
        if isinstance(c, dict) and c.get("index") == answer:
            return str(c.get("text") or "")
    if 1 <= answer <= len(choices):
        c = choices[answer - 1]
        return str(c.get("text") or "") if isinstance(c, dict) else str(c)
    return None


def _split_abc_blocks(body: str) -> tuple[str, dict[str, str]]:
    """
    [본문] 텍스트에서 (A)(B)(C) 블록을 분리한다.
    반환: (intro_before_A, {A: text, B: text, C: text})
    """
    matches = list(_ABC_BLOCK_RE.finditer(body))
    if not matches:
        return body.strip(), {}

    intro_before = body[: matches[0].start()].strip()
    blocks: dict[str, str] = {}
    for i, m in enumerate(matches):
        key = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        blocks[key] = body[start:end].strip()

    return intro_before, blocks


def _strip_circle_markers(text: str) -> str:
    """①②③④⑤ 마커(괄호 포함/미포함) 제거."""
    text = _CIRCLE_PAREN_RE.sub(" ", text)
    text = _CIRCLE_INLINE_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


# ────────────────────────────────────────────
# 유형별 정제 함수
# ────────────────────────────────────────────

def _refine_blank(passage: str, choices: list[Any] | None, answer: int | None) -> str:
    """빈칸 추론: _____ 을 정답 선택지 텍스트로 교체."""
    cleaned = _strip_section_labels(passage)
    if not _BLANK_RE.search(cleaned):
        return cleaned
    fill = _pick_choice_text(choices, answer)
    if fill:
        cleaned = _BLANK_RE.sub(fill, cleaned, count=1)
    return cleaned


def _refine_insertion(passage: str, answer: int | None) -> str:
    """문장 삽입: [제시문] 문장을 ( ①~⑤ ) 중 answer 위치에 삽입, 나머지 마커 제거."""
    intro, body = _split_intro_body(passage)

    if not body:
        return _strip_section_labels(passage)

    if not intro or answer is None or not (1 <= answer <= 5):
        cleaned = _CIRCLE_PAREN_RE.sub("", body)
        cleaned = _CIRCLE_INLINE_RE.sub("", cleaned)
        if intro:
            cleaned = intro + " " + cleaned
        return _WHITESPACE_RE.sub(" ", cleaned).strip()

    target_circle = CIRCLE_ORDER[answer - 1]

    def _replace(m: re.Match) -> str:
        return (" " + intro + " ") if m.group(1) == target_circle else " "

    refined = _CIRCLE_PAREN_RE.sub(_replace, body)

    # 괄호 없는 bare circle fallback
    if target_circle in refined:
        def _replace_bare(m: re.Match) -> str:
            return (" " + intro + " ") if m.group(0) == target_circle else " "
        refined = _CIRCLE_INLINE_RE.sub(_replace_bare, refined)

    return _WHITESPACE_RE.sub(" ", refined).strip()


def _refine_ordering(passage: str, choices: list[Any] | None, answer: int | None) -> str:
    """
    글의 순서: (A)(B)(C) 블록을 정답 순서로 재조합한다.
    [본문]에 블록이 없으면 [제시문] intro만 반환한다.
    """
    intro_sec, body = _split_intro_body(passage)

    if not body:
        # 데이터에 본문 없음 → intro만 사용
        return intro_sec or _strip_section_labels(passage)

    pre_intro, blocks = _split_abc_blocks(body)

    # (A)(B)(C) 블록이 없으면 레이블만 제거
    if not blocks:
        return _strip_section_labels(passage)

    # 정답 선택지에서 순서 추출: "(B) - (A) - (C)" → ['B', 'A', 'C']
    order: list[str] = []
    choice_text = _pick_choice_text(choices, answer)
    if choice_text:
        order = _ABC_ORDER_RE.findall(choice_text)

    # 순서 정보가 없으면 원래 순서 유지
    if not order:
        order = list(blocks.keys())

    # intro 조합: [제시문] intro > [본문] 첫 단락 > 없음
    lead = intro_sec or pre_intro

    parts = [lead] if lead else []
    for key in order:
        if key in blocks:
            parts.append(blocks[key])

    return "\n\n".join(parts).strip()


def _refine_irrelevant(passage: str, answer: int | None) -> str:
    """
    무관한 문장: ① ② ③ ④ ⑤ 번호가 붙은 문장 중 answer 번호 문장을 제거하고
    나머지 번호 마커도 제거한다.
    """
    cleaned = _strip_section_labels(passage)

    if answer is None or not (1 <= answer <= 5):
        return _strip_circle_markers(cleaned)

    target = CIRCLE_ORDER[answer - 1]

    # "① 문장 내용. ② 다음 문장" 형태 처리
    # 마커 앞뒤 공백 포함해서 분리
    pattern = re.compile(r"[①②③④⑤]")
    parts = pattern.split(cleaned)
    markers = pattern.findall(cleaned)

    if not markers:
        return cleaned

    # parts[0] = 마커 이전 텍스트, parts[1..] = 각 마커 이후 텍스트
    result_parts = [parts[0]]
    for marker, part in zip(markers, parts[1:]):
        if marker == target:
            continue  # 무관한 문장 제거
        result_parts.append(part)

    return _WHITESPACE_RE.sub(" ", "".join(result_parts)).strip()


def _refine_summary(passage: str, choices: list[Any] | None, answer: int | None) -> str:
    """
    요약문 완성: [본문]만 사용하고 [제시문](요약문 빈칸)은 제외한다.
    [제시문]의 (A)(B) 빈칸에 선택지를 채워 요약문을 붙이는 것도 가능하지만
    생성용 지문으로는 [본문]만으로 충분하다.
    """
    _, body = _split_intro_body(passage)
    return body or _strip_section_labels(passage)


def _refine_default(passage: str) -> str:
    """그 외 유형: 섹션 레이블만 제거."""
    return _strip_section_labels(passage)


# ────────────────────────────────────────────
# 공개 API
# ────────────────────────────────────────────

def refine_passage(
    passage: str,
    *,
    category_name: str = "",
    choices: list[Any] | None = None,
    answer: int | None = None,
) -> str:
    """
    수능 문제 지문을 유형에 맞게 정제해 반환한다.

    유형별 처리:
    - 빈칸 추론   : 정답 선택지로 _____ 교체
    - 문장 삽입   : 제시문을 정답 위치 ①~⑤ 에 삽입, 나머지 마커 제거
    - 글의 순서   : (A)(B)(C) 블록을 정답 순서로 재조합 (블록 없으면 intro만)
    - 무관한 문장 : answer 번호 문장 제거, 나머지 번호 마커 제거
    - 요약문 완성 : [본문]만 추출 ([제시문] 요약문 빈칸 제외)
    - 어법/지칭   : ①~⑤ 인라인 마커 제거
    - 기타        : [본문]/[제시문] 레이블만 제거
    """
    name = (category_name or "").strip()

    if "빈칸" in name:
        return _refine_blank(passage, choices, answer)
    if "삽입" in name:
        return _refine_insertion(passage, answer)
    if "순서" in name:
        return _refine_ordering(passage, choices, answer)
    if "무관" in name:
        return _refine_irrelevant(passage, answer)
    if "요약" in name:
        return _refine_summary(passage, choices, answer)
    if "어법" in name or "지칭" in name:
        return _strip_circle_markers(_strip_section_labels(passage))
    return _refine_default(passage)
