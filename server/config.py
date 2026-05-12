"""Single config surface. All env reads happen here."""
import os
from dataclasses import dataclass, field
from typing import List


VOICES_ALL = [
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "en-GB-RyanNeural",
    "en-GB-SoniaNeural",
    "en-IN-NeerjaNeural",
    "en-IN-PrabhatNeural",
    "zh-CN-XiaoxiaoNeural",
]


@dataclass
class Config:
    port: int = 8765
    claude_endpoint: str = "http://localhost:23333/api/anthropic/v1/messages"
    claude_model: str = "claude-opus-4.7-1m-internal"
    ai_backend: str = "claude"
    azure_endpoint: str = ""
    azure_api_version: str = "2025-04-01-preview"
    azure_api_key: str = ""
    azure_model: str = "gpt-5.4-mini"
    whisper_model: str = "small"
    voices: List[str] = field(default_factory=lambda: list(VOICES_ALL))
    curriculum_dir: str = "curriculum"
    data_dir: str = "data"


def load_config() -> Config:
    return Config(
        port=int(os.environ.get("SPEAKAGENT_PORT", "8765")),
        claude_endpoint=os.environ.get(
            "CLAUDE_API_ENDPOINT",
            "http://localhost:23333/api/anthropic/v1/messages",
        ),
        claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-4.7-1m-internal"),
        ai_backend=os.environ.get("AI_BACKEND", "claude").lower(),
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        azure_api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
        azure_api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
        azure_model=os.environ.get("AZURE_OPENAI_MODEL", "gpt-5.4-mini"),
        whisper_model=os.environ.get("WHISPER_MODEL", "small"),
    )


def voices_for_week(week: int) -> List[str]:
    """Returns the eligible voice pool for a given training week (1-8)."""
    if week <= 2:
        return ["en-US-AriaNeural", "en-US-GuyNeural"]
    if week <= 4:
        return [
            "en-US-AriaNeural", "en-US-GuyNeural",
            "en-GB-RyanNeural", "en-GB-SoniaNeural",
        ]
    if week <= 6:
        return list(VOICES_ALL)
    return list(VOICES_ALL)
