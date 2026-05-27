from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignUpRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    created_at: datetime


class SignUpResponse(BaseModel):
    message: str
    user: UserResponse


class LoginResponse(BaseModel):
    message: str
    user: UserResponse


class CommunityPostListResponse(BaseModel):
    id: int
    category: str
    title: str
    summary: str
    hours_ago: int
    time_ago: str
    views: int
    likes: int
    comments: int
    author: str
    authored_at: str


class CommunityPostDetailResponse(BaseModel):
    id: int
    category: str
    title: str
    summary: str
    body: str
    hours_ago: int
    time_ago: str
    views: int
    likes: int
    comments: int
    author: str
    authored_at: str
    is_liked: bool = False


class PostCreateRequest(BaseModel):
    author_id: int
    category: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=5000)


class CommentCreateRequest(BaseModel):
    author_id: int
    content: str = Field(min_length=1, max_length=1000)


class CommentResponse(BaseModel):
    id: int
    post_id: int
    author_id: int
    author: str
    content: str
    hours_ago: int
    time_ago: str
    authored_at: str


class LikeToggleRequest(BaseModel):
    user_id: int


class LikeToggleResponse(BaseModel):
    post_id: int
    liked: bool
    like_count: int


class DocumentUploadResponse(BaseModel):
    document_id: int
    user_id: int | None = None
    image_url: str


class DocumentUploadListResponse(BaseModel):
    documents: list[DocumentUploadResponse]
    total_count: int
    file_name: str


class DocumentOcrMockResponse(BaseModel):
    document_id: int
    status: str
    mock_item: dict[str, Any]
    items: list[dict[str, Any]] | None = None


class DocumentParseMockResponse(BaseModel):
    document_id: int
    analysis_run_id: int
    status: str


class DocumentParseStatusResponse(BaseModel):
    document_id: int
    analysis_run_id: int
    status: str
    result_json: dict[str, Any] | None = None
    error_message: str | None = None
