import json
import re
import urllib.error
import urllib.request
from typing import Any

from app.config import settings
from app.services.exam_parser.clients import call_exam_parser
from app.services.exam_parser.code_prefix import generate_code_prefix
from app.services.exam_parser.json_utils import JsonParseDiagnosticError, parse_and_clean_json
from app.services.exam_parser.prompt import ParsePromptMode, build_exam_parser_prompt


def _parse_json_object(raw: str) -> dict[str, Any]:
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
        -   If multiple clauses end simultaneously, use an array of strings like `[\"]\", \"]\"]`.
    -   `grammar_note`: If there's a specific grammatical point worth noting, write ONLY the grammatical term in Korean (e.g., '분사구문', '관계대명사', '과거분사', '부사절', 'to부정사'). Maximum 6 Korean characters. Do NOT include explanations, parentheses, full sentences, or English text.
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


def _validate_overlay_result(parsed: dict[str, Any]) -> dict[str, Any]:
    analysis_data = parsed.get("analysis_data")
    if not isinstance(analysis_data, dict) or not isinstance(analysis_data.get("sentences"), list):
        raise RuntimeError("AI 응답에 analysis_data.sentences가 없습니다.")
    return parsed


def _call_gemini_parse_overlay(*, code: str, topic: str, full_text: str, api_key: str | None = None, model: str | None = None) -> dict[str, Any]:
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


def _call_openrouter_parse_overlay(*, code: str, topic: str, full_text: str, api_key: str | None = None, model: str | None = None) -> dict[str, Any]:
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


def analyze_syntax_text(
    *,
    text: str,
    passage_code: str,
    topic_title: str,
    api_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    actual_provider = (provider or settings.ai_provider or "gemini").strip().lower()
    if actual_provider == "gemini":
        return _call_gemini_parse_overlay(
            code=passage_code,
            topic=topic_title,
            full_text=text,
            api_key=api_key,
            model=model,
        )
    if actual_provider == "openrouter":
        return _call_openrouter_parse_overlay(
            code=passage_code,
            topic=topic_title,
            full_text=text,
            api_key=api_key,
            model=model,
        )
    raise RuntimeError(f"지원하지 않는 AI_PROVIDER입니다: {actual_provider}")


def analyze_exam_image(
    *,
    image_base64: str,
    file_name: str,
    parse_mode: ParsePromptMode,
    code_prefix: str | None = None,
    api_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    resolved_code_prefix = code_prefix or generate_code_prefix(file_name)
    prompt = build_exam_parser_prompt(resolved_code_prefix, parse_mode)
    raw_text = call_exam_parser(
        image_base64=image_base64,
        prompt=prompt,
        api_key=api_key,
        provider=provider,
        model=model,
    )
    try:
        return parse_and_clean_json(raw_text)
    except JsonParseDiagnosticError:
        # Retry once with stricter instructions to reduce malformed JSON responses.
        retry_prompt = "\n\n".join(
            [
                prompt,
                "[RETRY JSON ONLY] Return exactly one valid JSON array.",
                "Do not use markdown code fences.",
                "Escape all double quotes inside string values as \\\".",
                "Do not omit commas between object fields or array elements.",
            ]
        )
        retry_raw_text = call_exam_parser(
            image_base64=image_base64,
            prompt=retry_prompt,
            api_key=api_key,
            provider=provider,
            model=model,
        )
        return parse_and_clean_json(retry_raw_text)


def _normalize_header_meta(raw: Any) -> dict[str, Any] | None:
    obj = raw[0] if isinstance(raw, list) and raw else raw
    if not isinstance(obj, dict):
        return None

    exam_label = str(obj.get("examLabel") or "").strip()
    if not exam_label:
        return None

    year_val = obj.get("year")
    month_val = obj.get("month")
    grade_val = obj.get("grade")

    year = int(year_val) if isinstance(year_val, (int, float)) else None
    month = int(month_val) if isinstance(month_val, (int, float)) else None
    grade = int(grade_val) if isinstance(grade_val, (int, float)) else None

    normalized_year = year if year is not None and 2000 <= year <= 2100 else None
    normalized_month = month if month is not None and 1 <= month <= 12 else None
    normalized_grade = grade if grade is not None and 1 <= grade <= 3 else None

    exam_id = str(obj.get("examId") or "").strip()
    if not exam_id and normalized_year and normalized_month and normalized_grade:
        exam_id = f"{normalized_year}-{str(normalized_month).zfill(2)}-G{normalized_grade}"

    return {
        "examLabel": exam_label,
        "examId": exam_id,
        "year": normalized_year,
        "month": normalized_month,
        "grade": normalized_grade,
    }


def analyze_exam_header_meta(
    *,
    image_base64: str,
    api_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any] | None:
    prompt = "\n".join(
        [
            "[ROLE] Extract official Korean CSAT English exam header metadata from image.",
            "[TASK]",
            "- Read only the visible top header text.",
            "- Return one JSON object with fields: examLabel, examId, year, month, grade.",
            "- examId format: YYYY-MM-GN (example: 2025-06-G3).",
            "- If a field is not inferable, use null.",
            "- Output ONLY JSON object. No markdown. No extra text.",
        ]
    )

    raw_text = call_exam_parser(
        image_base64=image_base64,
        prompt=prompt,
        api_key=api_key,
        provider=provider,
        model=model,
    )

    parsed = _parse_json_object(raw_text)
    return _normalize_header_meta(parsed)
