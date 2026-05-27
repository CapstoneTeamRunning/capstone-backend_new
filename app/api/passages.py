import csv
import json
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter(prefix="/passages", tags=["passages"])

BASE_DIR = Path(__file__).resolve().parents[2]
PASSAGES_JSON = BASE_DIR / "test_passages.json"
MANUAL_CSV = BASE_DIR / "passages_needs_manual.csv"

_cached_passages: list[dict] | None = None
_cached_manual_codes: set[str] | None = None


def _load_passages() -> list[dict]:
    global _cached_passages
    if _cached_passages is not None:
        return _cached_passages
    try:
        raw = PASSAGES_JSON.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="failed to load passages json")
    if not isinstance(parsed, list):
        raise HTTPException(status_code=500, detail="passages json format invalid")
    _cached_passages = parsed
    return parsed


def _load_manual_codes() -> set[str]:
    global _cached_manual_codes
    if _cached_manual_codes is not None:
        return _cached_manual_codes
    codes: set[str] = set()
    if not MANUAL_CSV.exists():
        _cached_manual_codes = codes
        return codes
    try:
        with MANUAL_CSV.open(encoding="utf-8") as fh:
            reader = csv.reader(fh)
            for row in reader:
                if not row:
                    continue
                # assume first column is code
                codes.add(str(row[0]).strip())
    except Exception:
        # ignore and return empty set
        codes = set()
    _cached_manual_codes = codes
    return codes


def _find_by_code(code: str) -> dict | None:
    for item in _load_passages():
        if str(item.get("code")) == code:
            return item
    return None


@router.get("/")
def list_passages(limit: int = Query(50, ge=1, le=1000), offset: int = Query(0, ge=0), filter: str = Query("all")) -> dict:
    items = _load_passages()
    total = len(items)
    manual_codes = _load_manual_codes()

    if filter in ("manual", "needs_manual"):
        sel = [it for it in items if str(it.get("code")) in manual_codes]
    else:
        sel = items

    slice_items = sel[offset : offset + limit]
    return {"total": total, "count": len(sel), "items": slice_items}


@router.get("/{code}")
def get_passage(code: str) -> dict:
    item = _find_by_code(code)
    if item is None:
        raise HTTPException(status_code=404, detail="passage not found")
    return item


@router.get("/manual/download")
def download_manual_csv():
    if not MANUAL_CSV.exists():
        raise HTTPException(status_code=404, detail="manual csv not found")
    return FileResponse(path=str(MANUAL_CSV), media_type="text/csv", filename=MANUAL_CSV.name)


@router.get("/report")
def report() -> dict:
    items = _load_passages()
    manual_codes = _load_manual_codes()
    total = len(items)
    manual_count = sum(1 for it in items if str(it.get("code")) in manual_codes)
    underscores = sum(1 for it in items if isinstance(it.get("content", {}).get("passage"), str) and "_" in it.get("content", {}).get("passage", ""))
    labels_count = sum(1 for it in items if isinstance(it.get("content", {}).get("passage"), str) and ("[" in it.get("content", {}).get("passage", "") or "]" in it.get("content", {}).get("passage", "")))
    return {"total": total, "manual_listed": len(manual_codes), "manual_count_in_items": manual_count, "underscores": underscores, "labels_like": labels_count}
