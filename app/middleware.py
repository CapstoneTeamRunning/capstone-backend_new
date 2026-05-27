from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def setup_middleware(app: FastAPI) -> None:
    """
    애플리케이션에 필요한 미들웨어를 설정합니다. (예: CORS)
    """
    # CORS 설정: 웹 브라우저(React)에서 들어오는 요청을 허용합니다.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 모든 출처 허용. 프로덕션에서는 특정 도메인으로 제한하는 것이 안전합니다.
        allow_credentials=True,
        allow_methods=["*"],  # 모든 HTTP 메소드 허용
        allow_headers=["*"],  # 모든 HTTP 헤더 허용
    )