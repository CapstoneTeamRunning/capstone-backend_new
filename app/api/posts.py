from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Comment, Post, PostLike, User
from app.schemas import (
    CommentCreateRequest,
    CommentResponse,
    LikeToggleRequest,
    LikeToggleResponse,
    PostCreateRequest,
    CommunityPostDetailResponse,
    CommunityPostListResponse,
)

router = APIRouter(prefix="/posts", tags=["posts"])


def _build_common_fields(post: Post, author: User) -> dict:
    created_at = post.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    delta_seconds = max(0, int((now - created_at).total_seconds()))
    hours_ago = delta_seconds // 3600
    minutes_ago = delta_seconds // 60
    if delta_seconds < 60:
        time_ago = "방금 전"
    elif delta_seconds < 3600:
        time_ago = f"{minutes_ago}분 전"
    else:
        time_ago = f"{hours_ago}시간 전"
    authored_at = created_at.astimezone().strftime("%Y.%-m.%-d.%H:%M")

    compact = " ".join(post.content.split())
    summary = compact if len(compact) <= 70 else f"{compact[:70].rstrip()}..."

    return {
        "id": post.id,
        "category": post.category,
        "title": post.title,
        "summary": summary,
        "hours_ago": hours_ago,
        "time_ago": time_ago,
        "views": post.view_count,
        "likes": post.like_count,
        "comments": post.comment_count,
        "author": author.username,
        "authored_at": authored_at,
    }


def _to_list_response(post: Post, author: User) -> CommunityPostListResponse:
    return CommunityPostListResponse(**_build_common_fields(post=post, author=author))


def _to_detail_response(
    post: Post,
    author: User,
    *,
    is_liked: bool = False,
) -> CommunityPostDetailResponse:
    return CommunityPostDetailResponse(
        **_build_common_fields(post=post, author=author),
        body=post.content,
        is_liked=is_liked,
    )


def _to_comment_response(comment: Comment, author: User) -> CommentResponse:
    created_at = comment.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta_seconds = max(0, int((now - created_at).total_seconds()))
    hours_ago = delta_seconds // 3600
    minutes_ago = delta_seconds // 60
    if delta_seconds < 60:
        time_ago = "방금 전"
    elif delta_seconds < 3600:
        time_ago = f"{minutes_ago}분 전"
    else:
        time_ago = f"{hours_ago}시간 전"
    authored_at = created_at.astimezone().strftime("%Y.%-m.%-d.%H:%M")
    return CommentResponse(
        id=comment.id,
        post_id=comment.post_id,
        author_id=comment.author_id,
        author=author.username,
        content=comment.content,
        hours_ago=hours_ago,
        time_ago=time_ago,
        authored_at=authored_at,
    )


@router.get("", response_model=list[CommunityPostListResponse])
def list_posts(
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[CommunityPostListResponse]:
    stmt = (
        select(Post, User)
        .join(User, User.id == Post.author_id)
        .where(Post.deleted_at.is_(None))
        .order_by(Post.created_at.desc())
    )

    if category:
        stmt = stmt.where(Post.category == category)

    rows = db.execute(stmt).all()
    return [_to_list_response(post=post, author=author) for post, author in rows]


@router.post("", response_model=CommunityPostDetailResponse, status_code=status.HTTP_201_CREATED)
def create_post(
    payload: PostCreateRequest,
    db: Session = Depends(get_db),
) -> CommunityPostDetailResponse:
    author = db.scalar(select(User).where(User.id == payload.author_id))
    if author is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="author not found")

    category = payload.category.strip()
    title = payload.title.strip()
    content = payload.content.strip()
    allowed_categories = {"문제풀이", "공부", "자유"}

    if category not in allowed_categories:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid category")
    if not title or not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title/content required")

    post = Post(
        author_id=payload.author_id,
        category=category,
        title=title,
        content=content,
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    return _to_detail_response(post=post, author=author, is_liked=False)


@router.get("/{post_id}", response_model=CommunityPostDetailResponse)
def get_post(
    post_id: int,
    user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CommunityPostDetailResponse:
    row = db.execute(
        select(Post, User)
        .join(User, User.id == Post.author_id)
        .where(Post.id == post_id, Post.deleted_at.is_(None))
    ).first()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="post not found")

    post, author = row
    is_liked = False
    if user_id is not None:
        is_liked = (
            db.scalar(
                select(PostLike.post_id).where(
                    PostLike.post_id == post_id,
                    PostLike.user_id == user_id,
                )
            )
            is not None
        )

    return _to_detail_response(post=post, author=author, is_liked=is_liked)


@router.get("/{post_id}/comments", response_model=list[CommentResponse])
def list_comments(post_id: int, db: Session = Depends(get_db)) -> list[CommentResponse]:
    post_exists = db.scalar(select(Post.id).where(Post.id == post_id, Post.deleted_at.is_(None)))
    if post_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="post not found")

    rows = db.execute(
        select(Comment, User)
        .join(User, User.id == Comment.author_id)
        .where(Comment.post_id == post_id, Comment.deleted_at.is_(None))
        .order_by(Comment.created_at.asc())
    ).all()
    return [_to_comment_response(comment=comment, author=author) for comment, author in rows]


@router.post(
    "/{post_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    post_id: int,
    payload: CommentCreateRequest,
    db: Session = Depends(get_db),
) -> CommentResponse:
    post = db.scalar(select(Post).where(Post.id == post_id, Post.deleted_at.is_(None)))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="post not found")

    author = db.scalar(select(User).where(User.id == payload.author_id))
    if author is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="author not found")

    comment = Comment(
        post_id=post_id,
        author_id=payload.author_id,
        content=payload.content.strip(),
    )
    db.add(comment)
    post.comment_count += 1
    db.commit()
    db.refresh(comment)

    return _to_comment_response(comment=comment, author=author)


@router.post("/{post_id}/like", response_model=LikeToggleResponse)
def toggle_like(
    post_id: int,
    payload: LikeToggleRequest,
    db: Session = Depends(get_db),
) -> LikeToggleResponse:
    post = db.scalar(select(Post).where(Post.id == post_id, Post.deleted_at.is_(None)))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="post not found")

    user = db.scalar(select(User).where(User.id == payload.user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    existing = db.scalar(
        select(PostLike).where(
            PostLike.post_id == post_id,
            PostLike.user_id == payload.user_id,
        )
    )

    if existing is None:
        db.add(PostLike(post_id=post_id, user_id=payload.user_id))
        post.like_count += 1
        liked = True
    else:
        db.delete(existing)
        post.like_count = max(0, post.like_count - 1)
        liked = False

    db.commit()

    return LikeToggleResponse(post_id=post_id, liked=liked, like_count=post.like_count)
