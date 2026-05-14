from unittest.mock import patch, MagicMock

import pytest

from autopilot.backlog import Item
from autopilot.runners.openhands_runner import (
    build_docker_command,
    spawn_openhands,
    to_posix_path,
)


def test_to_posix_converts_windows_drive():
    assert to_posix_path("D:\\repo\\foo\\bar") == "/d/repo/foo/bar"


def test_to_posix_converts_windows_forward_slashes():
    assert to_posix_path("D:/repo/foo") == "/d/repo/foo"


def test_to_posix_lowercases_drive():
    assert to_posix_path("C:/Users/x") == "/c/Users/x"


def test_to_posix_passthrough_for_unix_paths():
    assert to_posix_path("/home/user/repo") == "/home/user/repo"


def test_build_docker_command_includes_required_flags():
    item = Item(slug="my-task", priority=5, source="test", prompt="do the thing")
    cmd = build_docker_command(
        item, "/d/wt",
        openhands_image="oh:latest",
        runtime_image="rt:latest",
        llm_base_url="http://host.docker.internal:23333/x",
        llm_model="anthropic/claude-x",
        llm_api_key="key",
        max_iterations=42,
    )
    assert cmd[0] == "docker" and cmd[1] == "run"
    assert "--rm" in cmd
    assert "oh:latest" in cmd
    # Sandbox volume must use POSIX path with colon-separated mount spec
    assert any(
        e.startswith("SANDBOX_VOLUMES=/d/wt:/workspace:rw") for e in cmd
    )
    # Runtime image is passed via env so OpenHands main agent can spawn it
    assert any(
        e.startswith("SANDBOX_RUNTIME_CONTAINER_IMAGE=rt:latest") for e in cmd
    )
    # LLM wiring goes through env vars, not config file
    assert any(e.startswith("LLM_MODEL=anthropic/claude-x") for e in cmd)
    assert any(e.startswith("LLM_BASE_URL=http://host.docker.internal:") for e in cmd)
    assert any(e.startswith("LLM_API_KEY=key") for e in cmd)
    # Force a known custom provider so litellm picks the anthropic codepath
    assert "LLM_CUSTOM_LLM_PROVIDER=anthropic" in cmd
    # host.docker.internal hostname so container reaches the host gateway
    assert "host.docker.internal:host-gateway" in cmd
    # Iteration cap is forwarded
    assert "-i" in cmd and "42" in cmd
    # Prompt is the task argument
    t_idx = cmd.index("-t")
    assert cmd[t_idx + 1] == "do the thing"


def test_build_docker_command_uses_slug_for_container_name():
    item = Item(slug="my-cool-task", priority=1, source="t", prompt="x")
    cmd = build_docker_command(
        item, "/d/wt",
        openhands_image="oh", runtime_image="rt",
        llm_base_url="u", llm_model="m", llm_api_key="k",
        max_iterations=1,
    )
    name_idx = cmd.index("--name")
    assert "my-cool-task" in cmd[name_idx + 1]


def test_build_docker_command_explicit_container_name_overrides_slug():
    item = Item(slug="my-cool-task", priority=1, source="t", prompt="x")
    cmd = build_docker_command(
        item, "/d/wt",
        openhands_image="oh", runtime_image="rt",
        llm_base_url="u", llm_model="m", llm_api_key="k",
        max_iterations=1,
        container_name="explicit-name",
    )
    name_idx = cmd.index("--name")
    assert cmd[name_idx + 1] == "explicit-name"


def test_spawn_openhands_translates_windows_path_and_sets_msys_env(tmp_path):
    item = Item(slug="t", priority=1, source="s", prompt="p")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env", {})
        captured["timeout"] = kwargs.get("timeout")
        return MagicMock(returncode=0, stdout="trajectory…", stderr="")

    with patch("autopilot.runners.openhands_runner.subprocess.run",
               side_effect=fake_run):
        proc = spawn_openhands(item, "D:\\repo\\wt-foo")

    assert proc.returncode == 0
    # Path translated to POSIX before becoming part of SANDBOX_VOLUMES
    assert any("SANDBOX_VOLUMES=/d/repo/wt-foo:/workspace:rw" in c for c in captured["cmd"])
    # MSYS env var set so Git Bash on Windows doesn't mangle Linux paths
    assert captured["env"].get("MSYS_NO_PATHCONV") == "1"
    # Default 30 min timeout
    assert captured["timeout"] == 30 * 60


def test_spawn_openhands_returns_completed_process_shape(tmp_path):
    item = Item(slug="t", priority=1, source="s", prompt="p")
    fake = MagicMock(returncode=0, stdout="hi", stderr="")
    with patch("autopilot.runners.openhands_runner.subprocess.run",
               return_value=fake):
        proc = spawn_openhands(item, "/already/posix")
    # Loop only reads .returncode / .stdout / .stderr — verify they exist.
    assert proc.returncode == 0
    assert proc.stdout == "hi"
    assert proc.stderr == ""
