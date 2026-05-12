import json
from server.logging_setup import get_logger, configure_logging


def test_logger_emits_json(capsys):
    configure_logging()
    log = get_logger("test")
    log.info("hello", session_id="s1", latency_ms=42)
    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "hello"
    assert payload["session_id"] == "s1"
    assert payload["latency_ms"] == 42
