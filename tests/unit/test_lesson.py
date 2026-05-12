from server.lesson import load_lesson


def test_load_week1_day1(tmp_path):
    p = tmp_path / "lesson.yml"
    p.write_text(
        "id: w1d1\n"
        "title: Listening foundation\n"
        "week: 1\n"
        "turns:\n"
        "  - speaker: agent\n"
        "    say: Hello and welcome.\n"
        "  - speaker: user\n"
        "    prompt: Repeat after me.\n"
        "    ideal: Hello and welcome.\n",
        encoding="utf-8",
    )
    lp = load_lesson(str(p))
    assert lp.id == "w1d1"
    assert lp.week == 1
    assert len(lp.turns) == 2
    assert lp.turns[0]["speaker"] == "agent"
    assert lp.turns[1]["ideal"] == "Hello and welcome."
