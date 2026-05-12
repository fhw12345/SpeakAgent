"""Kill-switch sentinel. Presence of PAUSE file halts the autopilot loop."""
import os


def is_paused(pause_path: str = "autopilot/PAUSE") -> bool:
    return os.path.exists(pause_path)
