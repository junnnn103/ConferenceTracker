from datetime import date
from pathlib import Path

from scripts import report as rp

TODAY = date(2026, 10, 12)


def data(*confs):
    return {"conferences": list(confs)}


def conf(abbr, deadlines, start="2027-08-17"):
    return {"abbr": abbr, "editions": [{"year": 2027, "start": start, "end": start,
                                        "date_text": "", "place": "P", "deadlines": deadlines}]}


def test_diff_reports_field_level_changes():
    before = data(conf("ACL", [{"type": "paper", "label": "ARR", "date": "2027-01-04T23:59:59"}]))
    after = data(conf("ACL", [{"type": "paper", "label": "ARR", "date": "2027-01-04T23:59:59"},
                              {"type": "commitment", "label": "Commitment", "date": "2027-03-01T23:59:59"}]))
    changes = rp.diff_conferences(before, after)
    assert changes == [{"abbr": "ACL", "year": 2027, "field": "commitment: Commitment",
                        "old": None, "new": "2027-03-01"}]


def test_featured_and_upcoming_follow_the_site_rules():
    """본 논문 → 포스터/LBW → 워크숍 발표 순서, AoE는 KST로 하루 뒤."""
    c = conf("CHI", [
        {"type": "paper", "label": "Papers", "date": "2026-09-10T23:59:59", "timezone": "AoE"},
        {"type": "notification", "label": "List of accepted workshops", "date": "2026-10-15T23:59:59", "timezone": "AoE"},
        {"type": "poster", "label": "Posters", "date": "2026-10-20T23:59:59", "timezone": "AoE"},
    ], start="2027-05-10")
    upcoming = rp.upcoming_deadlines(data(c), TODAY)
    assert upcoming == [{"abbr": "CHI", "label": "Posters", "date": "2026-10-21", "dday": 9}]


def make_run(**over):
    base = dict(today=TODAY, targets=[], applied=[], changes=[], rejected=[], held=[],
                blocked=[], tba=[], failures=[], upcoming=[])
    base.update(over)
    return rp.RunResult(**base)


def test_nothing_to_say_means_no_message():
    assert not rp.should_send(make_run(upcoming=[{"abbr": "X", "label": "y", "date": "z", "dday": 1}]))
    assert rp.should_send(make_run(blocked=[{"abbr": "SIGGRAPH", "year": 2027}]))
    assert rp.should_send(make_run(failures=["pytest 실패"]))


def test_summary_fits_discord_and_flags_truncation():
    held = [{"abbr": f"C{i}", "year": 2027, "item": {"type": "poster", "date": "2027-01-01 00:00:00",
             "label": "x" * 80}, "review": None, "reasons": ["what:other"]} for i in range(60)]
    text, truncated = rp.render_summary(make_run(held=held))
    assert len(text) <= 2000 and truncated
    short, cut = rp.render_summary(make_run(blocked=[{"abbr": "SIGGRAPH", "year": 2027}]))
    assert not cut and "SIGGRAPH" in short


def test_send_attaches_full_report_only_when_truncated(tmp_path):
    calls = []

    class Done:
        returncode = 0

    def runner(cmd, **kw):
        calls.append(cmd)
        return Done()

    assert rp.send_discord("요약", tmp_path / "r.md", attach=True, runner=runner)
    assert calls[0][1:4] == ["send", "-t", "discord"]
    assert calls[0][4].endswith(f"MEDIA:{tmp_path / 'r.md'}")
    rp.send_discord("요약", tmp_path / "r.md", attach=False, runner=runner)
    assert "MEDIA:" not in calls[1][4]


def test_research_binary_falls_back_when_not_on_path(monkeypatch):
    monkeypatch.setattr(rp.shutil, "which", lambda name: None)
    assert rp.research_bin().endswith("/.local/bin/research")
