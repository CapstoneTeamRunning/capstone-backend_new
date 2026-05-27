from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from datetime import datetime
import uuid
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
SUPPORTED_INPUT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
IMAGE_INPUT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _load_dotenv_file(env_path: Path) -> None:
    # .env의 KEY=VALUE를 읽어, 현재 프로세스 환경변수가 비어 있을 때 채운다.
    if not env_path.exists() or not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        # 값 양끝의 작은/큰 따옴표를 허용한다.
        value = value.strip().strip('"').strip("'")
        if key and (key not in os.environ or not str(os.environ.get(key, "")).strip()):
            os.environ[key] = value


def _auto_detect_env_file() -> Path | None:
    # backend/.env를 우선 사용하고, 없으면 저장소 루트 .env를 사용한다.
    current = Path(__file__).resolve()
    repo_root = current.parents[2]
    backend_root = current.parents[1]

    candidates = [
        backend_root / ".env",
        repo_root / ".env",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _resolve_api_key(cli_api_key: str, provider: str) -> str:
    # 우선순위: CLI 인자 > provider별 환경변수
    if cli_api_key:
        return cli_api_key

    # 백엔드의 설정과 동일하게 맞춰주기 위해 환경변수에서 AI_PROVIDER를 읽어옵니다.
    env_provider = os.getenv("AI_PROVIDER", provider).lower()
    
    if env_provider == "openrouter":
        return os.getenv("OPENROUTER_API_KEY", "")
    return os.getenv("GEMINI_API_KEY", "")


def _encode_multipart_form(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    # 외부 의존성 없이 multipart/form-data 본문을 수동으로 구성한다.
    boundary = f"----parser-client-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")

    for file_field_name, file_path in files.items():
        if not file_path or not file_path.exists():
            continue
            
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        filename = file_path.name
        file_bytes = file_path.read_bytes()

        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{file_field_name}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8")
        )
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        chunks.append(file_bytes)
        chunks.append(b"\r\n")

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    return body, f"multipart/form-data; boundary={boundary}"


def _post_multipart(url: str, fields: dict[str, str], files: dict[str, Path]) -> dict:
    # analyze-file 요청 1회를 보내고 JSON 응답을 파싱한다.
    body, content_type = _encode_multipart_form(fields, files)
    req = urllib.request.Request(
        url=url,
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else str(exc)
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Connection failed: {exc.reason}") from exc


def parse_args() -> argparse.Namespace:
    # 백엔드 수동 테스트가 쉽도록 CLI 옵션을 단순하게 유지한다.
    parser = argparse.ArgumentParser(description="Test backend parser upload APIs")
    parser.add_argument("--file", default="", help="Path to image or PDF (single mode)")
    parser.add_argument("--inbox-dir", default="", help="Batch parse all files from this folder (default: root/backend/upload_inbox)")
    parser.add_argument("--recursive", action="store_true", help="Scan inbox folder recursively")
    parser.add_argument("--accum-log", default="", help="Accumulated JSON log file path for batch mode")
    parser.add_argument("--api-key", default="", help="API key (highest priority)")
    parser.add_argument("--provider", default="gemini", choices=["gemini", "openrouter"], help="AI provider")
    parser.add_argument("--model", default="gemini-2.5-flash", help="Model name")
    parser.add_argument(
        "--parse-mode",
        default=None,
        choices=["official", "user"],
        help="Parser mode (omit to choose interactively: 1=user, 2=official)",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Backend base URL")
    parser.add_argument("--env-file", default="", help="Optional .env file path")
    parser.add_argument("--code-prefix", default="", help="Optional explicit code prefix")
    parser.add_argument("--show-items", type=int, default=3, help="How many parsed items to preview")
    parser.add_argument(
        "--upload-api",
        default="split",
        choices=["split", "legacy"],
        help="split: use /analyze-upload/image|pdf, legacy: use /analyze-file",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output JSON path (default: <input_stem>.parsed.json next to input file)",
    )
    parser.add_argument(
        "--output-mode",
        default="items",
        choices=["items", "full"],
        help="items: save parsed item list only, full: save full API response",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print JSON payload to stdout",
    )
    return parser.parse_args()


def _resolve_upload_endpoint(file_path: Path, upload_api: str, base_url: str) -> str:
    base = base_url.rstrip("/")
    if upload_api == "legacy":
        return f"{base}/parser/exam/analyze-file"

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return f"{base}/parser/exam/analyze-upload/pdf"
    if suffix in IMAGE_INPUT_EXTENSIONS:
        return f"{base}/parser/exam/analyze-upload/image"
    raise ValueError(f"Unsupported file extension: {suffix}")


def _resolve_output_path(input_file: Path, explicit_output: str) -> Path:
    # 기본 출력 파일은 입력 파일 옆에 생성해 찾기 쉽게 한다.
    if explicit_output:
        return Path(explicit_output)
    return input_file.with_name(f"{input_file.stem}.parsed.json")


def _resolve_batch_output_path(input_file: Path, output_dir: Path) -> Path:
    # 배치 모드 결과 파일은 지정 폴더에 모아 저장한다.
    safe_stem = input_file.stem.replace(" ", "_")
    return output_dir / f"{safe_stem}.parsed.json"


def _resolve_accum_log_path(explicit_path: str) -> Path:
    # 누적 로그 경로를 지정하지 않으면 backend/tmp 아래 기본 파일을 사용한다.
    if explicit_path:
        return Path(explicit_path)
    return Path(__file__).resolve().parents[1] / "tmp" / "parser_accumulated_log.json"


def _load_accumulated_records(path: Path) -> list[dict]:
    if not path.exists() or not path.is_file():
        return []

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    return parsed if isinstance(parsed, list) else []


def _append_accumulated_record(path: Path, record: dict) -> None:
    records = _load_accumulated_records(path)
    records.append(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _collect_inbox_files(inbox_dir: Path, recursive: bool) -> list[Path]:
    if not inbox_dir.exists() or not inbox_dir.is_dir():
        return []

    candidates = inbox_dir.rglob("*") if recursive else inbox_dir.glob("*")
    files = [p for p in candidates if p.is_file() and p.suffix.lower() in SUPPORTED_INPUT_EXTENSIONS]
    return sorted(files, key=lambda p: p.name.lower())


def _select_parse_mode_interactive() -> str:
    # 실행 시 빠르게 모드를 고르도록 1/2 입력을 받는다.
    print("\n모드를 선택하세요:")
    print("  1) 유저(user)")
    print("  2) 공식(official)")

    while True:
        choice = input("선택 (1/2): ").strip()
        if choice == "1":
            return "user"
        if choice == "2":
            return "official"
        print("[WARN] 1 또는 2만 입력하세요.")


def _parse_single_file(
    file_path: Path,
    args: argparse.Namespace,
    parse_mode: str,
    api_key: str,
    provider: str,
    model: str,
    code_prefix: str,
    env_file: Path | None,
    output_path: Path,
) -> tuple[bool, dict]:
    try:
        url = _resolve_upload_endpoint(file_path, args.upload_api, args.base_url)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return False, {"error": str(exc)}

    fields = {
        "parse_mode": parse_mode,
        "api_key": api_key,
        "provider": provider,
        "model": model,
    }
    if code_prefix:
        fields["code_prefix"] = code_prefix

    print(f"[INFO] POST {url}")
    print(f"[INFO] file={file_path.name} provider={provider} model={model} mode={parse_mode}")
    print(f"[INFO] upload_api={args.upload_api}")
    
    files_to_upload = {"file": file_path}
    if parse_mode == "official":
        answer_p = file_path.with_name(f"{file_path.stem}_answer.txt")
        if answer_p.exists():
            print(f"[INFO] answer_file found: {answer_p.name}")
            files_to_upload["answer_file"] = answer_p

    if code_prefix:
        print(f"[INFO] code_prefix={code_prefix}")
    if env_file:
        print(f"[INFO] env_file={env_file}")

    try:
        payload = _post_multipart(url, fields, files_to_upload)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return False, {"error": str(exc)}

    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        print("[ERROR] Unexpected response shape")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return False, {"error": "Unexpected response shape", "payload": payload}

    print("\n[OK] response summary")
    print(f"- source_type: {payload.get('source_type')}")
    print(f"- page_count: {payload.get('page_count')}")
    print(f"- parsed_page_count: {payload.get('parsed_page_count')}")
    print(f"- items: {len(items)}")
    assessment = payload.get("assessment") if isinstance(payload, dict) else None
    if isinstance(assessment, dict):
        print(
            "- assessment: "
            f"verdict={assessment.get('verdict')} "
            f"score={assessment.get('officialScore')}/{assessment.get('maxScore')} "
            f"hardPassed={assessment.get('hardPassed')}"
        )

    preview_count = max(0, min(args.show_items, len(items)))
    if preview_count > 0:
        print(f"\n[PREVIEW] first {preview_count} items")
        for idx in range(preview_count):
            item = items[idx]
            number = item.get("number")
            code = item.get("code")
            category = (item.get("category") or {}).get("name")
            print(f"  {idx + 1}. number={number} code={code} category={category}")

    output_payload = items if args.output_mode == "items" else payload
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] JSON saved: {output_path}")

    if args.print_json:
        print("\n[JSON]")
        print(json.dumps(output_payload, ensure_ascii=False, indent=2))

    return True, {
        "source_type": payload.get("source_type"),
        "page_count": payload.get("page_count"),
        "parsed_page_count": payload.get("parsed_page_count"),
        "items_count": len(items),
        "assessment": assessment if isinstance(assessment, dict) else None,
        "saved_path": str(output_path),
    }


def main() -> int:
    # 1) 환경변수/키 결정 2) API 호출 3) 요약 출력 4) JSON 파일 저장.
    args = parse_args()

    # --env-file가 있으면 명시 경로를 쓰고, 없으면 자동 탐지한다.
    env_file = Path(args.env_file) if args.env_file else _auto_detect_env_file()
    if env_file:
        _load_dotenv_file(env_file)

    api_key = _resolve_api_key(args.api_key, args.provider)
    if not api_key:
        print("[ERROR] API key is required")
        print("        - --api-key <KEY>")
        print("        - or .env: GEMINI_API_KEY / OPENROUTER_API_KEY")
        return 1

    # .env 파일에 설정된 provider와 model이 있다면 우선 사용합니다. (명령줄 인자가 기본값이면 덮어씌움)
    provider = os.getenv("AI_PROVIDER", args.provider).lower()
    model = os.getenv("AI_MODEL", args.model)

    parse_mode = args.parse_mode
    # --parse-mode를 생략하면 터미널 입력(1/2)으로 모드를 선택하고,
    # 비대화형 실행에서는 유저 모드(user)로 기본 처리한다.
    if not parse_mode:
        if sys.stdin.isatty():
            parse_mode = _select_parse_mode_interactive()
        else:
            parse_mode = "user"

    code_prefix = args.code_prefix
    if parse_mode == "user" and not code_prefix:
        # 요청사항: 유저 모드 기본 아이디는 apitest 사용.
        code_prefix = "apitest"

    # 파일이나 인박스가 명시되지 않으면 스크립트 위치 기준으로 기본 inbox 폴더 사용
    if not args.file and not args.inbox_dir:
        args.inbox_dir = str(Path(__file__).resolve().parents[1] / "upload_inbox")

    if args.inbox_dir:
        inbox_dir = Path(args.inbox_dir)
        files = _collect_inbox_files(inbox_dir, args.recursive)
        if not files:
            print(f"[WARN] inbox folder has no supported files: {inbox_dir}")
            return 0

        output_dir = Path(args.output) if args.output else inbox_dir / "parsed"
        accum_log_path = _resolve_accum_log_path(args.accum_log)

        print(f"[INFO] inbox mode: {len(files)} files")
        print(f"[INFO] inbox_dir={inbox_dir}")
        print(f"[INFO] output_dir={output_dir}")
        print(f"[INFO] accum_log={accum_log_path}")

        success_count = 0
        for idx, file_path in enumerate(files, start=1):
            print(f"\n===== [{idx}/{len(files)}] {file_path.name} =====")
            out_path = _resolve_batch_output_path(file_path, output_dir)
            ok, summary = _parse_single_file(
                file_path=file_path,
                args=args,
                parse_mode=parse_mode,
                api_key=api_key,
                provider=provider,
                model=model,
                code_prefix=code_prefix,
                env_file=env_file,
                output_path=out_path,
            )

            record = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "file_name": file_path.name,
                "file_path": str(file_path),
                "parse_mode": parse_mode,
                "provider": provider,
                "model": model,
                "status": "success" if ok else "failed",
                "result": summary,
            }
            _append_accumulated_record(accum_log_path, record)
            if ok:
                success_count += 1

        print(f"\n[OK] batch completed: {success_count}/{len(files)} success")
        print(f"[OK] accumulated log: {accum_log_path}")
        return 0 if success_count == len(files) else 4

    if not args.file:
        print("[ERROR] --file is required in single mode (or use --inbox-dir)")
        return 1

    file_path = Path(args.file)
    if not file_path.exists() or not file_path.is_file():
        print(f"[ERROR] file not found: {file_path}")
        return 1

    output_path = _resolve_output_path(file_path, args.output)
    ok, _summary = _parse_single_file(
        file_path=file_path,
        args=args,
        parse_mode=parse_mode,
        api_key=api_key,
        provider=provider,
        model=model,
        code_prefix=code_prefix,
        env_file=env_file,
        output_path=output_path,
    )
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
