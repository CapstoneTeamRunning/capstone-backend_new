import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.config import settings


def _strip_data_url_prefix(image_base64: str) -> str:
    if "," in image_base64:
        return image_base64.split(",", 1)[1]
    return image_base64


def _to_openrouter_image_url(image_base64: str) -> str:
    candidate = image_base64.strip()
    if candidate.startswith("http://") or candidate.startswith("https://"):
        return candidate
    if candidate.startswith("data:"):
        return candidate
    return f"data:image/png;base64,{_strip_data_url_prefix(candidate)}"


def _resolve_provider(provider: str | None) -> str:
    return (provider or settings.ai_provider or "gemini").strip().lower()


def _resolve_model(model: str | None, provider: str) -> str:
    if model:
        return model.strip()
    if provider == "openrouter":
        return "google/gemini-2.0-flash-001"
    return settings.ai_model or "gemini-2.0-flash"


def _resolve_api_key(provider: str, api_key: str | None) -> str:
    if api_key and api_key.strip():
        return api_key.strip()
    if provider == "openrouter":
        key = settings.openrouter_api_key.strip()
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY가 비어 있습니다.")
        return key
    key = settings.gemini_api_key.strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY가 비어 있습니다.")
    return key


def _map_openrouter_model(model: str) -> str:
    model_map = {
        "gemini-3.1-pro-preview": "google/gemini-3.1-pro-preview",
        "gemini-3-flash-preview": "google/gemini-3-flash-preview",
        "gemini-3.1-flash-lite-preview": "google/gemini-3.1-flash-lite-preview",
        "gemini-2.5-flash": "google/gemini-2.5-flash",
        "gemini-2.5-pro": "google/gemini-2.5-pro",
        "gemini-2.0-flash": "google/gemini-2.0-flash-001",
    }
    return model_map.get(model, model)


def call_exam_parser(
    *,
    image_base64: str,
    prompt: str,
    api_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    actual_provider = _resolve_provider(provider)
    actual_model = _resolve_model(model, actual_provider)
    actual_api_key = _resolve_api_key(actual_provider, api_key)

    if actual_provider == "gemini":
        return _call_gemini(image_base64=image_base64, prompt=prompt, api_key=actual_api_key, model=actual_model)
    if actual_provider == "openrouter":
        mapped_model = _map_openrouter_model(actual_model)
        return _call_openrouter(image_base64=image_base64, prompt=prompt, api_key=actual_api_key, model=mapped_model)

    raise RuntimeError(f"지원하지 않는 provider입니다: {actual_provider}")


def _call_gemini(*, image_base64: str, prompt: str, api_key: str, model: str) -> str:
    url_model = urllib.parse.quote(model, safe="")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{url_model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": _strip_data_url_prefix(image_base64),
                        }
                    },
                    {"text": "Parse the questions in this image according to the rules."},
                ],
            }
        ],
        "generationConfig": {"responseMimeType": "application/json"},
    }

    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else str(exc)
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gemini 연결 실패: {exc.reason}") from exc

    candidates = body.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini 응답에 candidates가 없습니다.")

    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    texts = [p.get("text") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]
    text = "\n".join(texts).strip()
    if not text:
        raise RuntimeError("Gemini 응답 본문이 비어 있습니다.")
    return text


def _call_openrouter(*, image_base64: str, prompt: str, api_key: str, model: str) -> str:
    payload = {
        "model": model,
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": prompt,
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Parse the questions in this image according to the rules."},
                    {"type": "image_url", "image_url": {"url": _to_openrouter_image_url(image_base64)}},
                ],
            },
        ],
    }

    req = urllib.request.Request(
        url="https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Capstone Exam Parser API",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            body: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else str(exc)
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter 연결 실패: {exc.reason}") from exc

    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("OpenRouter 응답 구조가 예상과 다릅니다.") from exc

    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("OpenRouter 응답 본문이 비어 있습니다.")
    return text
