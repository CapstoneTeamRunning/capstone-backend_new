from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def ensure_user_stats(db: Session, user_id: int) -> dict[str, Any] | None:
    db.execute(
        text(
            """
            INSERT INTO user_stats (user_id, total_uploaded_count, total_generated_count, updated_at)
            SELECT
                :user_id,
                (SELECT COUNT(*) FROM documents WHERE user_id = :user_id),
                (
                    SELECT COUNT(*)
                    FROM questions q
                    JOIN ocr_results o ON o.id = q.ocr_result_id
                    JOIN documents d ON d.id = o.document_id
                    WHERE d.user_id = :user_id
                      AND q.source_type = 'generated'
                ),
                now()
            WHERE EXISTS (SELECT 1 FROM users WHERE id = :user_id)
            ON CONFLICT (user_id) DO NOTHING
            """
        ),
        {"user_id": user_id},
    )
    row = db.execute(
        text(
            """
            SELECT user_id, total_uploaded_count, total_generated_count
            FROM user_stats
            WHERE user_id = :user_id
            """
        ),
        {"user_id": user_id},
    ).mappings().first()
    return dict(row) if row is not None else None


def increment_total_uploaded_count(db: Session, user_id: int) -> None:
    db.execute(
        text(
            """
            INSERT INTO user_stats (user_id, total_uploaded_count, total_generated_count, updated_at)
            SELECT
                :user_id,
                (SELECT COUNT(*) FROM documents WHERE user_id = :user_id),
                (
                    SELECT COUNT(*)
                    FROM questions q
                    JOIN ocr_results o ON o.id = q.ocr_result_id
                    JOIN documents d ON d.id = o.document_id
                    WHERE d.user_id = :user_id
                      AND q.source_type = 'generated'
                ),
                now()
            ON CONFLICT (user_id) DO UPDATE
            SET total_uploaded_count = user_stats.total_uploaded_count + 1,
                updated_at = now()
            """
        ),
        {"user_id": user_id},
    )


def increment_total_generated_count(db: Session, user_id: int) -> None:
    db.execute(
        text(
            """
            INSERT INTO user_stats (user_id, total_uploaded_count, total_generated_count, updated_at)
            SELECT
                :user_id,
                (SELECT COUNT(*) FROM documents WHERE user_id = :user_id),
                (
                    SELECT COUNT(*)
                    FROM questions q
                    JOIN ocr_results o ON o.id = q.ocr_result_id
                    JOIN documents d ON d.id = o.document_id
                    WHERE d.user_id = :user_id
                      AND q.source_type = 'generated'
                ),
                now()
            ON CONFLICT (user_id) DO UPDATE
            SET total_generated_count = user_stats.total_generated_count + 1,
                updated_at = now()
            """
        ),
        {"user_id": user_id},
    )
