#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from sqlalchemy import func, select


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Comment, Post, PostLike, User  # noqa: E402
from app.security import hash_password  # noqa: E402


def get_or_create_user(db, username: str, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user:
        return user

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.flush()
    return user


def get_or_create_post(
    db,
    *,
    author: User,
    category: str,
    title: str,
    content: str,
    hours_ago: int,
    view_count: int,
) -> Post:
    post = db.scalar(
        select(Post).where(
            Post.author_id == author.id,
            Post.title == title,
        )
    )
    if post:
        return post

    created_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    post = Post(
        author_id=author.id,
        category=category,
        title=title,
        content=content,
        view_count=view_count,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(post)
    db.flush()
    return post


def get_or_create_comment(
    db,
    *,
    post: Post,
    author: User,
    content: str,
    hours_ago: int,
) -> Comment:
    existing = db.scalar(
        select(Comment).where(
            Comment.post_id == post.id,
            Comment.author_id == author.id,
            Comment.content == content,
        )
    )
    if existing:
        return existing

    created_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    comment = Comment(
        post_id=post.id,
        author_id=author.id,
        content=content,
        created_at=created_at,
    )
    db.add(comment)
    db.flush()
    return comment


def get_or_create_like(db, *, post: Post, user: User) -> None:
    existing = db.scalar(
        select(PostLike).where(
            PostLike.post_id == post.id,
            PostLike.user_id == user.id,
        )
    )
    if existing:
        return

    db.add(PostLike(post_id=post.id, user_id=user.id))
    db.flush()


def recalc_post_counters(db) -> None:
    posts = db.scalars(select(Post)).all()
    for post in posts:
        comment_count = db.scalar(
            select(func.count(Comment.id)).where(
                Comment.post_id == post.id,
                Comment.deleted_at.is_(None),
            )
        ) or 0
        like_count = db.scalar(
            select(func.count()).select_from(PostLike).where(PostLike.post_id == post.id)
        ) or 0
        post.comment_count = int(comment_count)
        post.like_count = int(like_count)


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # 1) users
        users = {
            "reading_master": get_or_create_user(
                db, "reading_master", "master@example.com", "password123"
            ),
            "logic_runner": get_or_create_user(
                db, "logic_runner", "logic@example.com", "password123"
            ),
            "voca_habit": get_or_create_user(
                db, "voca_habit", "voca@example.com", "password123"
            ),
            "study_mate": get_or_create_user(
                db, "study_mate", "mate@example.com", "password123"
            ),
        }

        # 2) posts
        seed_posts = [
            (
                "문제풀이",
                "빈칸 추론 정확도 올리는 루틴 공유",
                "지문을 읽고 바로 답 고르기보다, 연결사/지시어를 먼저 밑줄치면 오답이 확 줄었습니다. "
                "저는 1) 연결사 체크 2) 빈칸 앞뒤 문장 관계 확인 3) 선택지 소거 순으로 풀고 있습니다.",
                "reading_master",
                2,
                132,
            ),
            (
                "문제풀이",
                "순서 배열 문제에서 시간 줄이는 팁",
                "처음부터 모든 문장을 비교하면 오래 걸립니다. 첫 문장 후보를 1~2개로 좁힌 뒤, "
                "접속사와 대명사 연결을 기준으로 빠르게 확정하면 시간이 많이 단축됩니다.",
                "logic_runner",
                5,
                94,
            ),
            (
                "공부",
                "오답노트 템플릿 공유 (어휘/논리 분리)",
                "오답 이유를 어휘 부족/논리 오해/실수로 나눠 기록하면 복습 우선순위를 잡기 쉽습니다. "
                "저는 주 2회 오답노트 회독으로 약점 보완 중입니다.",
                "voca_habit",
                8,
                76,
            ),
            (
                "공부",
                "매일 30분 리딩 루틴 추천",
                "아침 15분(짧은 지문), 저녁 15분(오답 복습)으로 고정해보세요. "
                "꾸준히 하면 지문 속도랑 정확도가 같이 올라갑니다.",
                "study_mate",
                13,
                63,
            ),
            (
                "자유",
                "오늘 학습 인증 스레드",
                "오늘 푼 문제 수/복습한 내용 짧게 공유해요. 서로 체크해주면 루틴 유지에 도움이 됩니다!",
                "reading_master",
                1,
                58,
            ),
            (
                "자유",
                "다음 주 스터디원 모집",
                "월/수/금 저녁 9시, 40분 동안 문제풀이+해설 공유하는 소규모 스터디 모집합니다.",
                "logic_runner",
                19,
                41,
            ),
        ]

        posts_by_title: dict[str, Post] = {}
        for category, title, content, author_key, hours_ago, view_count in seed_posts:
            posts_by_title[title] = get_or_create_post(
                db,
                author=users[author_key],
                category=category,
                title=title,
                content=content,
                hours_ago=hours_ago,
                view_count=view_count,
            )

        # 3) comments
        seed_comments = [
            ("빈칸 추론 정확도 올리는 루틴 공유", "study_mate", "연결사 먼저 보는 방식 저도 효과 좋았어요!", 1),
            ("빈칸 추론 정확도 올리는 루틴 공유", "voca_habit", "선택지 소거 기준도 자세히 알려주실 수 있나요?", 1),
            ("순서 배열 문제에서 시간 줄이는 팁", "reading_master", "첫 문장 후보 좁히기 진짜 핵심이네요.", 3),
            ("오답노트 템플릿 공유 (어휘/논리 분리)", "logic_runner", "분류 기준 깔끔해서 바로 써볼게요.", 6),
            ("오늘 학습 인증 스레드", "voca_habit", "저는 오늘 12문제 풀었습니다!", 1),
            ("다음 주 스터디원 모집", "study_mate", "참여 희망합니다. 시간대 좋아요.", 11),
        ]
        for post_title, username, content, hours_ago in seed_comments:
            get_or_create_comment(
                db,
                post=posts_by_title[post_title],
                author=users[username],
                content=content,
                hours_ago=hours_ago,
            )

        # 4) likes
        seed_likes = [
            ("빈칸 추론 정확도 올리는 루틴 공유", "study_mate"),
            ("빈칸 추론 정확도 올리는 루틴 공유", "logic_runner"),
            ("빈칸 추론 정확도 올리는 루틴 공유", "voca_habit"),
            ("순서 배열 문제에서 시간 줄이는 팁", "reading_master"),
            ("순서 배열 문제에서 시간 줄이는 팁", "study_mate"),
            ("오답노트 템플릿 공유 (어휘/논리 분리)", "reading_master"),
            ("오답노트 템플릿 공유 (어휘/논리 분리)", "study_mate"),
            ("매일 30분 리딩 루틴 추천", "logic_runner"),
            ("오늘 학습 인증 스레드", "reading_master"),
            ("오늘 학습 인증 스레드", "logic_runner"),
            ("오늘 학습 인증 스레드", "voca_habit"),
            ("다음 주 스터디원 모집", "study_mate"),
        ]
        for post_title, username in seed_likes:
            get_or_create_like(db, post=posts_by_title[post_title], user=users[username])

        recalc_post_counters(db)
        db.commit()
        print("Seed completed: users/posts/comments/likes inserted (idempotent).")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

