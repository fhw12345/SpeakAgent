"""OpenHands runner: drop-in replacement for `_spawn_claude`.

Invokes `docker run … openhands/openhands python -m openhands.core.main`
in headless mode against a freshly-prepared worktree. Returns a
`subprocess.CompletedProcess` with the same shape `_spawn_claude` returns,
so the autopilot loop can swap runners without other code changes.

Path translation: the autopilot worktree path is a Windows path like
`D:/repo/.../wt-foo`. Docker on Windows refuses that as a `-v` source
because of the colon. We convert to POSIX (`/d/repo/.../wt-foo`) before
passing as `SANDBOX_VOLUMES`.

Trajectory: stdout (full ACTION/OBSERVATION stream) is captured in the
returned CompletedProcess. The autopilot logger already truncates with
stdout_tail; if the caller wants the full log they can re-read it from
`autopilot/runs/<date>-<slug>/trajectory.log` (caller's responsibility
to write — the runner just returns the bytes).
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Optional

from autopilot.backlog import Item


_DEFAULT_OPENHANDS_IMAGE = os.environ.get(
    "OPENHANDS_IMAGE",
    "docker.all-hands.dev/all-hands-ai/openhands:latest",
)
_DEFAULT_RUNTIME_IMAGE = os.environ.get(
    "OPENHANDS_RUNTIME_IMAGE",
    "docker.all-hands.dev/all-hands-ai/runtime:latest-nikolaik",
)
_DEFAULT_LLM_BASE_URL = os.environ.get(
    "OPENHANDS_LLM_BASE_URL",
    "http://host.docker.internal:23333/api/anthropic",
)
_DEFAULT_LLM_MODEL = os.environ.get(
    "OPENHANDS_LLM_MODEL",
    "anthropic/claude-opus-4.7-1m-internal[1m]",
)
_DEFAULT_LLM_API_KEY = os.environ.get(
    "OPENHANDS_LLM_API_KEY",
    "Powered by Agent Maestro",
)
_DEFAULT_MAX_ITERATIONS = int(os.environ.get("OPENHANDS_MAX_ITERATIONS", "30"))
_DEFAULT_TIMEOUT_S = int(os.environ.get("OPENHANDS_TIMEOUT_S", str(60 * 30)))


def to_posix_path(win_path: str) -> str:
    """Convert a Windows path to Docker-friendly POSIX form.

    `D:\\repo\\foo` or `D:/repo/foo` -> `/d/repo/foo`.
    Already-POSIX paths pass through unchanged.
    """
    p = win_path.replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    if m:
        drive = m.group(1).lower()
        rest = m.group(2)
        return f"/{drive}/{rest}"
    return p


def build_docker_command(
    item: Item,
    worktree_posix: str,
    *,
    openhands_image: str,
    runtime_image: str,
    llm_base_url: str,
    llm_model: str,
    llm_api_key: str,
    max_iterations: int,
    container_name: Optional[str] = None,
) -> list[str]:
    """Construct the `docker run …` argv. Pure function — easy to unit-test."""
    name = container_name or f"openhands-autopilot-{item.slug}"
    return [
        "docker", "run", "--rm",
        "--name", name,
        "-e", f"SANDBOX_RUNTIME_CONTAINER_IMAGE={runtime_image}",
        "-e", f"LLM_MODEL={llm_model}",
        "-e", f"LLM_API_KEY={llm_api_key}",
        "-e", f"LLM_BASE_URL={llm_base_url}",
        "-e", "LLM_CUSTOM_LLM_PROVIDER=anthropic",
        "-e", "LLM_DISABLE_VISION=true",
        "-e", f"SANDBOX_VOLUMES={worktree_posix}:/workspace:rw",
        "-e", "SANDBOX_USER_ID=0",
        "-e", "LOG_ALL_EVENTS=true",
        "-v", "//var/run/docker.sock:/var/run/docker.sock",
        "--add-host", "host.docker.internal:host-gateway",
        openhands_image,
        "python", "-m", "openhands.core.main",
        "-t", item.prompt,
        "-i", str(max_iterations),
        "--log-level", "INFO",
    ]


def spawn_openhands(
    item: Item,
    worktree: str,
    *,
    openhands_image: str = _DEFAULT_OPENHANDS_IMAGE,
    runtime_image: str = _DEFAULT_RUNTIME_IMAGE,
    llm_base_url: str = _DEFAULT_LLM_BASE_URL,
    llm_model: str = _DEFAULT_LLM_MODEL,
    llm_api_key: str = _DEFAULT_LLM_API_KEY,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> subprocess.CompletedProcess:
    """Drop-in replacement for `_spawn_claude(item, worktree)`."""
    worktree_posix = to_posix_path(worktree)
    cmd = build_docker_command(
        item, worktree_posix,
        openhands_image=openhands_image,
        runtime_image=runtime_image,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        max_iterations=max_iterations,
    )
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        env=env,
    )
