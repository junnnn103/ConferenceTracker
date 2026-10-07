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


def test_rendering_tolerates_missing_keys():
    """Missing keys in entries must not raise; must render with .get() defaults."""
    # Test held with missing keys
    held_incomplete = [{"abbr": "X"}]
    run = make_run(held=held_incomplete)
    summary, _ = rp.render_summary(run)
    assert summary  # Should not raise
    report = rp.render_report(run)
    assert report  # Should not raise

    # Test rejected with missing keys
    rejected_incomplete = [{}]
    run = make_run(rejected=rejected_incomplete)
    summary, _ = rp.render_summary(run)
    assert summary
    report = rp.render_report(run)
    assert report

    # Test applied with missing keys
    applied_incomplete = [{"abbr": "Y"}]
    run = make_run(applied=applied_incomplete)
    summary, _ = rp.render_summary(run)
    assert summary
    report = rp.render_report(run)
    assert report

    # Test tba with missing keys
    tba_incomplete = [{"abbr": "Z"}]
    run = make_run(tba=tba_incomplete)
    summary, _ = rp.render_summary(run)
    assert summary
    report = rp.render_report(run)
    assert report


def test_send_discord_handles_timeout():
    """send_discord must catch TimeoutExpired and return False."""
    def timeout_runner(cmd, **kw):
        raise rp.subprocess.TimeoutExpired(cmd="x", timeout=1)

    result = rp.send_discord("요약", Path("/test.md"), attach=False, runner=timeout_runner)
    assert result is False


def test_send_discord_handles_file_not_found():
    """send_discord must catch FileNotFoundError and return False."""
    def file_error_runner(cmd, **kw):
        raise FileNotFoundError("test")

    result = rp.send_discord("요약", Path("/test.md"), attach=False, runner=file_error_runner)
    assert result is False


def test_final_message_with_attachment_fits_discord_limit():
    """Final Discord message (summary + attachment line) must be <= 2000 chars."""
    held = [{"abbr": f"C{i}", "year": 2027, "item": {"type": "poster", "date": "2027-01-01 00:00:00",
             "label": "x" * 80}, "review": None, "reasons": ["what:other"]} for i in range(60)]
    run = make_run(held=held)
    summary, truncated = rp.render_summary(run)
    assert truncated

    # Simulate what send_discord does
    attachment_line = f"\nMEDIA:/Users/jay/.hermes/reports/conference-tracker/2026-10-12.md"
    final_message = summary + attachment_line
    assert len(final_message) <= 2000


def test_upcoming_deadlines_preserved_after_truncation():
    """Truncated summary with many held items must still include upcoming deadlines."""
    held = [{"abbr": f"C{i}", "year": 2027, "item": {"type": "poster", "date": "2027-01-01 00:00:00",
             "label": "x" * 80}, "review": None, "reasons": ["what:other"]} for i in range(60)]
    upcoming = [
        {"abbr": "CHI", "label": "Posters", "date": "2026-10-21", "dday": 9},
        {"abbr": "SIGCHI", "label": "Papers", "date": "2026-10-22", "dday": 10},
    ]
    run = make_run(held=held, upcoming=upcoming)
    summary, truncated = rp.render_summary(run)
    assert truncated
    assert "[14일 안 마감]" in summary
    assert "CHI" in summary
    assert "SIGCHI" in summary


def test_rejected_only_run_sends_nothing_but_rejected_still_reported():
    """설계 §10: 바뀐 것도 실패도 없으면 보내지 않는다. 게이트 탈락만으로는 보내지 않는다."""
    rejected = [{"abbr": "CHI", "year": 2027, "item": {"type": "notification"}, "reason": "forbidden_word"}]
    assert not rp.should_send(make_run(rejected=rejected))
    run = make_run(rejected=rejected, failures=["x"])
    assert rp.should_send(run)
    assert "forbidden_word" in rp.render_summary(run)[0]
