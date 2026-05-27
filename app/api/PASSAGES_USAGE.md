**Passages API 사용법**

- **파일 위치**: [backend/app/api/passages.py](backend/app/api/passages.py)
- **데이터 원본**: [backend/test_passages.json](backend/test_passages.json), [backend/passages_needs_manual.csv](backend/passages_needs_manual.csv)

**간단 소개**
- **목적**: 기존 코드 수정을 최소화하여 `test_passages.json`(파일 기반)을 읽고 간단한 조회·보고·수동검토 CSV 다운로드 기능을 제공하는 라우터입니다.

**엔드포인트**
- **GET /passages**: 목록 조회
  - **쿼리**: `limit`(기본50), `offset`(기본0), `filter`(all|manual)
  - **응답**: `{ "total": <전체건수>, "count": <선택된건수>, "items": [ ... ] }`
- **GET /passages/{code}**: 코드로 단건 조회
  - **성공**: 해당 문항 전체 JSON 반환
  - **실패(404)**: "passage not found"
- **GET /passages/manual/download**: `passages_needs_manual.csv` 파일 직접 다운로드
- **GET /passages/report**: 간단 통계 반환
  - 반환 예: `{ "total": 756, "manual_listed": 133, "manual_count_in_items": 133, "underscores": 127, "labels_like": 194 }`

**동작 원리(간단)**
- 서버 시작 시 DB나 별도 로드 과정 없이 요청 시점에 `backend/test_passages.json`을 읽어 캐시합니다.
- `passages_needs_manual.csv`가 존재하면 코드 목록을 읽어 `filter=manual`에 사용합니다.

**빠른 사용 예시**
```bash
# 목록 조회 (기본 50개)
curl "http://localhost:8000/passages"

# 수동검토 대상만 조회
curl "http://localhost:8000/passages?filter=manual&limit=100"

# 단건 조회
curl "http://localhost:8000/passages/P12345"

# 수동 CSV 다운로드
curl -OJ "http://localhost:8000/passages/manual/download"
```

**주의 및 확장 포인트**
- 현재는 파일 기반으로 동작하므로 대규모 운영에서는 DB로 이관하는 것을 권장합니다.
- AI 복원이나 배치 처리는 별도의 엔드포인트(`ai_restore`, `batch`)로 확장할 수 있습니다. 구현 패턴은 `backend/app/api/documents.py`의 `_call_parse_overlay`와 `BackgroundTasks`를 참고하세요.

**파일 참조**
- 라우터: [backend/app/api/passages.py](backend/app/api/passages.py)
- 메인 등록: [backend/app/main.py](backend/app/main.py)
- 데이터 샘플: [backend/test_passages.json](backend/test_passages.json)
- 수동 목록: [backend/passages_needs_manual.csv](backend/passages_needs_manual.csv)

**문의**
- 더 작은 범위(예: 페이징 개선, 쿼리 필터 추가) 또는 DB 마이그레이션을 원하시면 옵션을 골라주세요.
