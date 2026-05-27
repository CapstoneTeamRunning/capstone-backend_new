# Parser API 가이드 및 테스트 방법

본 프로젝트의 시험지 자동 파싱 API는 백엔드에서 작동하며, 파일 업로드/페이지 단위 분석/헤더 메타 추출을 지원합니다.
앱 또는 웹 클라이언트 개발자는 백엔드 `parser_api_client.py` 스크립트를 통해 실제 API 요청 방식과 응답 형태를 쉽게 테스트하고 참고할 수 있습니다.

---

## 1. 백엔드 Parser API 요약

현재 시험지 파싱 관련 엔드포인트는 5개입니다.

- `POST /parser/exam/analyze-upload/image` (multipart 이미지 업로드)
- `POST /parser/exam/analyze-upload/pdf` (multipart PDF 업로드)
- `POST /parser/exam/analyze-file` (레거시 통합 multipart 업로드)
- `POST /parser/exam/analyze-image` (base64 이미지 1장 파싱)
- `POST /parser/exam/header-meta` (base64 이미지에서 시험 메타 추출)

### 1-(-1). 실행 전 환경 준비

- Python 3.13 기준 테스트 완료
- 필수 패키지 설치:
   - `py -3.13 -m pip install -r backend/requirements.txt`
- PDF 업로드/분할 파싱은 `pymupdf==1.27.2.2`를 사용합니다.
   - 구버전 `pymupdf`에서 `metadata-generation-failed`가 발생하면 requirements 재설치로 버전을 맞추세요.

### 1-0. official 모드와 user 모드 차이

- `official` 모드:
   - 수능/모의고사 같은 공식 시험지 데이터 구축용 모드입니다.
   - 정답 파일(`*_answer.txt`) 매핑, 공식 판정(`assessment`) 등 관리자/개발자 작업에 필요한 검증 흐름을 포함합니다.
   - 운영 기준상 공식 시험지에만 사용하는 것을 권장합니다.

- `user` 모드:
   - 앱/웹에서 일반 사용자가 올리는 개인 문제집 사진, 개인 시험지 사진, 또는 사용자 PDF를 처리하는 모드입니다.
   - 실사용 업로드 중심으로 빠르게 파싱해 JSON을 얻는 흐름에 맞춰져 있습니다.
   - 사용자 식별이 필요하면 `code_prefix`에 user ID(예: `user123`)를 넣어 문항 코드 접두어로 사용하세요.
   - 공식 DB 구축보다는 개인 학습/보관/분석용 업로드에 적합합니다.

### 1-0-1. 프롬프트 파일 위치 (프롬프트 작성자용)

- 메인 파싱 프롬프트: `backend/app/services/exam_parser/prompt.py`
- 핵심 구성:
   - `_SHARED_CORE_PROMPT`: 공통 규칙/JSON 템플릿
   - `_OFFICIAL_APPENDIX`: official 모드 추가 규칙
   - `_USER_APPENDIX`: user 모드 추가 규칙
   - `build_exam_parser_prompt(...)`: 최종 프롬프트 조합 함수

### 1-1. 분리 업로드 파싱 (권장)

기본 권장 방식은 파일 타입별로 엔드포인트를 분리해 호출하는 것입니다.

- 이미지 파일(`.png`, `.jpg`, `.jpeg`, `.webp`): `POST /parser/exam/analyze-upload/image`
- PDF 파일(`.pdf`): `POST /parser/exam/analyze-upload/pdf`

- **Content-Type**: `multipart/form-data`
- **Form Data 필드**:
   - `file` (필수): 업로드 파일
   - `answer_file` (선택): 정답 데이터 텍스트 파일 (`.txt`, 형식 `문항번호: 정답번호`)
   - `parse_mode` (선택): `"user"` 또는 `"official"` (기본 `official`)
   - `api_key` (선택): Gemini/OpenRouter API Key
   - `provider` (선택): `"gemini"` 또는 `"openrouter"`
   - `model` (선택): 모델명
   - `code_prefix` (선택): user 모드 문항 코드 접두어

- **제약 사항**:
   - 최대 업로드 크기: 10MB
   - 이미지 엔드포인트 허용 확장자: `.png`, `.jpg`, `.jpeg`, `.webp`
   - PDF 엔드포인트 허용 확장자: `.pdf`

### 1-2. 레거시 통합 업로드 (`POST /parser/exam/analyze-file`)

이전 호환을 위해 단일 엔드포인트도 유지합니다.

- **Endpoint**: `POST /parser/exam/analyze-file`
- **Content-Type**: `multipart/form-data`
- **Form Data 필드**:
  - `file` (필수): 파싱할 시험지 파일 (PDF, PNG, JPG, WEBP).
  - `answer_file` (선택): 정답 데이터가 포함된 텍스트 파일 (`.txt`). 공식 모드 사용 시 문항별 정답을 자동으로 주입합니다 (형식: `문항번호: 정답번호`).
   - `parse_mode` (선택): `"user"` (앱용 유저 모드) 또는 `"official"` (관리자 공식 시험지 모드). 기본값은 `official`.
   - `api_key` (선택): Gemini 또는 OpenRouter API Key. 미지정 시 서버 환경변수 사용.
  - `provider` (선택): `"gemini"` 또는 `"openrouter"`.
  - `model` (선택): 사용할 AI 모델 모델명.
  - `code_prefix` (선택): 유저 모드에서 문항 코드 생성 시 접두어로 사용할 문자열 (예: 유저 ID).

- **유저 ID 권장 방식 (`user` 모드)**:
   - 앱/웹에서 로그인한 user ID를 `code_prefix`로 전달하는 것을 권장합니다.
   - 예: `code_prefix=user123`
   - 이렇게 하면 생성되는 코드에 사용자 구분자가 반영되어 추적/집계가 쉬워집니다.

- **제약 사항**:
   - 최대 업로드 크기: 10MB
   - 허용 확장자: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`

**응답(JSON)의 주요 필드**:
- `source_type`: 업로드된 원본의 타입 (예: "image" 또는 "pdf").
- `page_count`: 원본 PDF의 총 페이지 수 (이미지인 경우 1).
- `parsed_page_count`: 실제 분석이 진행된 페이지 수.
- `items`: 파싱된 문항 데이터 배열(리스트). 각 문항은 `number`, `question_text`, `choices`, `category`, `code` 등의 필드를 가집니다.
- `assessment` (official 모드): 백엔드 공식 판정 결과(`hardPassed`, `officialScore`, `verdict`, `checks`).

- **official 모드 필터링 동작**:
   - 문항 번호 `18~45`만 유지
   - 지문 지시문에 `다음을 듣고`, `대화를 듣고` 패턴이 있으면 제외

### 1-3. 이미지 1장 파싱 (`POST /parser/exam/analyze-image`)

- **Content-Type**: `application/json`
- **요청 예시 필드**:
   - `image_base64` (필수)
   - `file_name` (선택, 기본 `unknown`)
   - `parse_mode` (선택, 기본 `official`)
   - `code_prefix`, `api_key`, `provider`, `model` (선택)
- **응답**: 파싱된 문항 배열(`list[dict]`)

### 1-4. 헤더 메타 추출 (`POST /parser/exam/header-meta`)

- **Content-Type**: `application/json`
- **요청 예시 필드**:
   - `image_base64` (필수)
   - `api_key`, `provider`, `model` (선택)
- **응답**: 메타 정보 객체 또는 `null`

### 1-5. 빠른 curl 테스트 예시

아래 예시는 백엔드가 `http://127.0.0.1:8000`에서 실행 중이라고 가정합니다.

#### A-1) 이미지 업로드 파싱 (official)

```bash
curl -X POST "http://127.0.0.1:8000/parser/exam/analyze-upload/image" \
   -F "file=@backend/upload_inbox/sample_page.png" \
   -F "parse_mode=official" \
   -F "provider=openrouter" \
   -F "model=google/gemini-2.0-flash-001" \
   -F "api_key=YOUR_API_KEY"
```

#### A-2) PDF 업로드 파싱 (official)

```bash
curl -X POST "http://127.0.0.1:8000/parser/exam/analyze-upload/pdf" \
   -F "file=@backend/upload_inbox/sample_exam.pdf" \
   -F "parse_mode=official" \
   -F "provider=openrouter" \
   -F "model=google/gemini-2.0-flash-001" \
   -F "api_key=YOUR_API_KEY"
```

#### A-3) 레거시 통합 업로드 파싱 (호환용)

```bash
curl -X POST "http://127.0.0.1:8000/parser/exam/analyze-file" \
   -F "file=@backend/upload_inbox/sample_exam.pdf" \
   -F "parse_mode=official" \
   -F "provider=openrouter" \
   -F "model=google/gemini-2.0-flash-001" \
   -F "api_key=YOUR_API_KEY"
```

#### B) 이미지 1장 파싱 (base64 JSON)

```bash
curl -X POST "http://127.0.0.1:8000/parser/exam/analyze-image" \
   -H "Content-Type: application/json" \
   -d '{
      "image_base64": "BASE64_IMAGE_STRING",
      "file_name": "page_02.png",
      "parse_mode": "official",
      "provider": "openrouter",
      "model": "google/gemini-2.0-flash-001",
      "api_key": "YOUR_API_KEY"
   }'
```

#### B-1) 이미지 1장 파싱 (user + user ID)

```bash
curl -X POST "http://127.0.0.1:8000/parser/exam/analyze-image" \
   -H "Content-Type: application/json" \
   -d '{
      "image_base64": "BASE64_IMAGE_STRING",
      "file_name": "my_note_page.png",
      "parse_mode": "user",
      "code_prefix": "user123",
      "provider": "openrouter",
      "model": "google/gemini-2.0-flash-001",
      "api_key": "YOUR_API_KEY"
   }'
```

#### C) 헤더 메타 추출

```bash
curl -X POST "http://127.0.0.1:8000/parser/exam/header-meta" \
   -H "Content-Type: application/json" \
   -d '{
      "image_base64": "BASE64_IMAGE_STRING",
      "provider": "openrouter",
      "model": "google/gemini-2.0-flash-001",
      "api_key": "YOUR_API_KEY"
   }'
```

#### 참고

- PowerShell에서는 `curl`이 `Invoke-WebRequest` 별칭으로 동작할 수 있어, Git Bash/WSL curl 사용 또는 `curl.exe`를 권장합니다.
- 응답이 길면 `| jq`를 붙여 확인하면 편합니다.

---

## 2. API 테스트 스크립트 사용법 (`parser_api_client.py`)

앱 개발 환경과 무관하게, 순수 백엔드와 AI 간의 연결 상태를 가장 쉽게 테스트할 수 있도록 제공되는 CLI용 스크립트입니다.

### 실행 환경 설정
스크립트를 실행하기 위해선 파이썬(표준 라이브러리 urllib/mimetypes 기반) 환경이 필요하며, 백엔드 서버가 로컬(혹은 특정 URL)에 켜져 있어야 합니다.

1. **백엔드 서버 구동** (예: `python backend/app/main_webtest.py`)
2. **`backend/.env` 설정**: `.env` 파일에 발급받은 API 키(`OPENROUTER_API_KEY` 혹은 `GEMINI_API_KEY`)를 입력합니다. 모델 세팅(`AI_PROVIDER`, `AI_MODEL`)도 여기서 읽어갑니다.

### 기본 사용법 (배치 모드)

가장 간단한 테스트 방법입니다. 따로 옵션을 주지 않으면 대량 처리 모드(Batch mode)로 작동하며,
파일 확장자에 따라 아래 엔드포인트를 자동 선택합니다.

- 이미지: `POST /parser/exam/analyze-upload/image`
- PDF: `POST /parser/exam/analyze-upload/pdf`

1. `backend/upload_inbox` 폴더 안에 테스트할 PDF나 이미지 파일을 여러 개 넣습니다. 
   - 공식 모드의 경우 `파일이름_answer.txt` (예: `2026_exam_answer.txt`)를 같이 넣어두면 자동으로 스캔하여 정답을 매핑합니다.
2. 터미널(명령 프롬프트 또는 파워쉘)을 엽니다.
3. 아래 명령어를 실행합니다.
   ```bash
   python backend/scripts/parser_api_client.py
   ```
4. 실행 시 모드(`1: user` 또는 `2: official`)를 선택하라는 프롬프트가 나옵니다.
5. 파싱이 진행되며, 완료된 JSON 결과물은 `backend/upload_inbox/parsed/` 안에 각 파일 이름으로 저장됩니다.

### 개별 파일 모드

특정 파일 1개만 찍어서 파싱해보고 싶다면 `--file` 옵션을 사용하세요.

```bash
python backend/scripts/parser_api_client.py --file backend/upload_inbox/my_exam.pdf --parse-mode official
```

### 레거시 엔드포인트 강제 사용

레거시 통합 경로(`/parser/exam/analyze-file`)로 테스트하려면 `--upload-api legacy` 옵션을 사용하세요.

```bash
python backend/scripts/parser_api_client.py --file backend/upload_inbox/my_exam.pdf --parse-mode official --upload-api legacy
```

### 업로드 API 선택 옵션 (`--upload-api`)

- `split` (기본값): 파일 확장자 기반 자동 분기
   - 이미지(`.png/.jpg/.jpeg/.webp`) -> `/parser/exam/analyze-upload/image`
   - PDF(`.pdf`) -> `/parser/exam/analyze-upload/pdf`
- `legacy`: 레거시 단일 경로 강제 사용
   - 모든 지원 파일 -> `/parser/exam/analyze-file`

예시:

```bash
python backend/scripts/parser_api_client.py --file backend/upload_inbox/sample_page.png --upload-api split
python backend/scripts/parser_api_client.py --file backend/upload_inbox/sample_exam.pdf --upload-api legacy
```

### 클라이언트 개발 참고용

앱(또는 프론트엔드)에서 `multipart/form-data`를 구성해 전송하는 로직이 헷갈리신다면, `parser_api_client.py` 내부의 `_encode_multipart_form` 함수나 `_post_multipart` 함수가 데이터를 엮어 보내는 과정을 참고하시길 바랍니다. 외부 라이브러리 없이 표준 HTTP 요청을 어떻게 구성했는지 확인하실 수 있습니다.
