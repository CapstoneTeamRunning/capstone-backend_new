from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.user_stats import ensure_user_stats

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}/stats", response_model=dict)
def get_user_stats(user_id: int, db: Session = Depends(get_db)) -> dict:
    stats = ensure_user_stats(db, user_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="user not found")
    db.commit()
    return stats
