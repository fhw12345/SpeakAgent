from autopilot.killswitch import is_paused


def test_pause_absent_means_not_paused(tmp_path):
    assert is_paused(str(tmp_path / "PAUSE")) is False


def test_pause_present_means_paused(tmp_path):
    p = tmp_path / "PAUSE"
    p.write_text("")
    assert is_paused(str(p)) is True
