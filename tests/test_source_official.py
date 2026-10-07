from datetime import date, datetime

from scripts.sources.official import load_official, merge_official_doc, write_official

APPROVED = {
    "edition": {"date_text": "August 17-22, 2027", "start": "2027-08-17", "end": "2027-08-22",
                "place": "Kyoto, Japan", "evidence": {"raw_text": "Kyoto, Japan August 17–22, 2027",
                                                       "url": "https://2027.aclweb.org/"}},
    "deadlines": [{"type": "paper", "label": "ARR submission deadline", "date": "2027-01-04 23:59:59",
                   "timezone": "AoE", "evidence": {"raw_text": "ARR ... January 4, 2027",
                                                    "url": "https://2027.aclweb.org/calls/main/"}}],
}


def test_roundtrip(tmp_path):
    doc = merge_official_doc(None, "acl", 2027, APPROVED, date(2026, 10, 12))
    write_official(tmp_path / "acl.yaml", doc)
    (tmp_path / "checklog.yaml").write_text("acl/2027: {}\n", encoding="utf-8")
    loaded = load_official(tmp_path)
    off = loaded[("acl", 2027)]
    assert off.start == date(2027, 8, 17) and off.place == "Kyoto, Japan"
    assert off.deadlines[0].date == datetime(2027, 1, 4, 23, 59, 59)
    assert off.deadlines[0].source == "official"
    assert off.deadlines[0].evidence["url"] == "https://2027.aclweb.org/calls/main/"
    assert len(loaded) == 1, "checklog.yaml은 출처가 아니다"


def test_later_run_keeps_what_it_did_not_recheck():
    """D 기준만 다시 본 주에 회차 정보가 빠졌다고 지우면 안 된다."""
    first = merge_official_doc(None, "acl", 2027, APPROVED, date(2026, 10, 12))
    commitment = {"edition": None, "deadlines": [{
        "type": "commitment", "label": "Commitment deadline", "date": "2027-03-01 23:59:59",
        "timezone": "AoE", "evidence": {"raw_text": "...", "url": "https://2027.aclweb.org/"}}]}
    second = merge_official_doc(first, "acl", 2027, commitment, date(2026, 10, 19))
    block = second["editions"][0]
    assert block["edition"]["start"] == "2027-08-17"
    assert sorted(d["type"] for d in block["deadlines"]) == ["commitment", "paper"]
    assert block["checked"] == "2026-10-19"


def test_new_value_of_same_type_replaces_old():
    first = merge_official_doc(None, "acl", 2027, APPROVED, date(2026, 10, 12))
    moved = {"edition": None, "deadlines": [{**APPROVED["deadlines"][0], "date": "2027-01-06 23:59:59"}]}
    second = merge_official_doc(first, "acl", 2027, moved, date(2026, 10, 19))
    assert [d["date"] for d in second["editions"][0]["deadlines"]] == ["2027-01-06 23:59:59"]
