import sys
from pathlib import Path

# 부모 디렉토리를 sys.path에 추가 (직접 실행 시 import 경로 해결)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import auth, health, parser, posts
from app.api import documents_webtest as documents
from app.db import Base, engine
from app.middleware import setup_middleware

app = FastAPI(title="Capstone API", version="0.1.0")

# CORS 등 미들웨어 설정 분리
setup_middleware(app)


@app.on_event("startup")
def on_startup() -> None:
    #Base.metadata.create_all(bind=engine)
    pass


# 라우터 등록
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(posts.router)
app.include_router(documents.router)
app.include_router(parser.router)

base_dir = Path(__file__).resolve().parents[1]
uploads_dir = base_dir / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
