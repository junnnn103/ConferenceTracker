from datetime import date

from scripts.checklog import entry_key, is_due, load_checklog, record, save_checklog

TODAY = date(2026, 10, 12)


def test_never_checked_is_due():
    assert is_due(None, "C", TODAY, urgent=False)


def test_weekly_criteria_come_back_after_seven_days():
    entry = {"last_checked": "2026-10-05", "results": {}}
    assert is_due(entry, "A", TODAY, urgent=False)
    assert not is_due({**entry, "last_checked": "2026-10-06"}, "A", TODAY, urgent=False)


def test_c_none_is_never_due_again_for_that_edition():
    """NeurIPS처럼 포스터 제출 트랙이 아예 없는 학회를 매주 읽지 않는다."""
    entry = {"last_checked": "2026-01-01", "results": {"C": "none"}}
    assert not is_due(entry, "C", TODAY, urgent=False)
    assert is_due({**entry, "results": {"C": "tba"}}, "C", TODAY, urgent=False)


def test_e_is_four_weekly_unless_a_deadline_is_near():
    entry = {"last_checked": "2026-09-28", "results": {"E": "found"}}
    assert not is_due(entry, "E", TODAY, urgent=False)
    assert is_due(entry, "E", TODAY, urgent=True)
    assert is_due({**entry, "last_checked": "2026-09-14"}, "E", TODAY, urgent=False)


def test_record_and_roundtrip(tmp_path):
    log = {}
    record(log, "acl", 2027, TODAY, ["D"], {"D": "tba"}, "ok", ["ARR commitment deadline"], False)
    path = tmp_path / "checklog.yaml"
    save_checklog(path, log)
    loaded = load_checklog(path)
    entry = loaded[entry_key("acl", 2027)]
    assert entry["last_checked"] == "2026-10-12"
    assert entry["next_due"] == "2026-10-19"
    assert entry["tba"] == ["ARR commitment deadline"]
