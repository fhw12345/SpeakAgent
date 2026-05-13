"""GET /api/lessons — returns the 56-lesson course catalog."""
from fastapi import APIRouter

from server.lesson_catalog import build_catalog

router = APIRouter()


@router.get("/api/lessons")
def get_lessons():
    return {"lessons": build_catalog()}
