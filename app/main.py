from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import auth, documents, exam_sets, health, parser, posts, passages, question_generation, users
from app.db import Base, engine
from app.middleware import setup_middleware
from pathlib import Path

app = FastAPI(title="Capstone API", version="0.1.0")
setup_middleware(app)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


# 라우터 등록
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(posts.router)
app.include_router(documents.router)
app.include_router(question_generation.router)
app.include_router(users.router)
app.include_router(exam_sets.router)
app.include_router(parser.router)
app.include_router(passages.router)

base_dir = Path(__file__).resolve().parents[1]
uploads_dir = base_dir / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")
