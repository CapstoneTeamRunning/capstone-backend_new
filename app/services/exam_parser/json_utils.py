import json
import re
from typing import Any


class JsonParseDiagnosticError(RuntimeError):
    def __init__(self, message: str, diagnostics: dict[str, str]):
        detail = "\n".join(f"- {k}: {v}" for k, v in diagnostics.items())
        super().__init__(f"{message}\n{detail}")
        self.diagnostics = diagnostics


def _normalize_parsed_json(parsed: Any) -> list[dict[str, Any]]:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("questions"), list):
        return parsed["questions"]
    if isinstance(parsed, dict):
        return [parsed]
    raise ValueError("AI 응답 JSON이 object/array 형식이 아닙니다.")


def _summarize(value: str, max_len: int = 700) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized if len(normalized) <= max_len else f"{normalized[:max_len]}..."


def _remove_trailing_commas(text: str) -> str:
    """Remove trailing commas before '}' or ']' while respecting JSON strings."""
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == ",":
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] in "]}":
                i += 1
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def _loads_with_repair(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        repaired = _remove_trailing_commas(text)
        if repaired != text:
            return json.loads(repaired)
        raise


def parse_and_clean_json(text: str) -> list[dict[str, Any]]:
    clean_text = text.strip()
    diagnostics: dict[str, str] = {"response_length": str(len(text))}

    md_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_text)
    if md_match:
        clean_text = md_match.group(1)
        diagnostics["detected_markdown_block"] = "true"

    try:
        return _normalize_parsed_json(_loads_with_repair(clean_text))
    except Exception as exc:
        diagnostics["direct_parse_error"] = str(exc)

    first_bracket = clean_text.find("[")
    last_bracket = clean_text.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        candidate = clean_text[first_bracket : last_bracket + 1]
        try:
            return _normalize_parsed_json(_loads_with_repair(candidate))
        except Exception as exc:
            diagnostics["array_candidate_error"] = str(exc)

    first_brace = clean_text.find("{")
    last_brace = clean_text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = clean_text[first_brace : last_brace + 1]
        try:
            return _normalize_parsed_json(_loads_with_repair(candidate))
        except Exception as exc:
            diagnostics["object_candidate_error"] = str(exc)
            clean_text = candidate

    clean_text = re.sub(r"\\([^\"\\/bfnrtu])", r"\\\\\1", clean_text)

    try:
        return _normalize_parsed_json(_loads_with_repair(clean_text))
    except Exception as exc:
        diagnostics["final_parse_error"] = str(exc)
        diagnostics["raw_response_preview"] = _summarize(text)
        diagnostics["cleaned_response_preview"] = _summarize(clean_text)
        raise JsonParseDiagnosticError("Invalid JSON response from AI", diagnostics) from exc
