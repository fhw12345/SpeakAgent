"""GET /config — exposes runtime feature flags to the frontend."""
from fastapi import APIRouter

from server.config import load_config

router = APIRouter()


@router.get("/config")
def get_config():
    cfg = load_config()
    return {"vad": cfg.vad}
