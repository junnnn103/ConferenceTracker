from datetime import date

from scripts.gaps import displayed_edition, official_key, select_targets, triggered

TODAY = date(2026, 10, 12)


def ed(year, start=None, end=None, deadlines=(), source="ccfddl", link=None, **extra):
    return {"year": year, "start": start, "end": end or start, "deadlines": list(deadlines),
            "source": source, "link": link, "primary_deadline": None, **extra}


def dl(type_, date_, label="x"):
    return {"type": type_, "date": f"{date_}T23:59:59", "label": label}


def conf(abbr, editions, group=None, homepage="https://example.org/"):
    return {"abbr": abbr, "abbr_group": group or abbr.lower(), "full_name": abbr,
            "homepage": homepage, "editions": editions}


def test_a_estimated_edition():
    e = ed(2027, source="estimated", estimated_month=7)
    assert triggered(e, TODAY, None) == ["A"]


def test_b_no_main_deadline():
    e = ed(2027, "2027-06-01", deadlines=[dl("notification", "2027-03-01")])
    assert triggered(e, TODAY, None) == ["B"]


def test_c_paper_closed_and_nothing_else_before_the_conference():
    e = ed(2026, "2026-12-01", deadlines=[dl("paper", "2026-05-01")])
    assert triggered(e, TODAY, None) == ["C"]
    with_poster = ed(2026, "2026-12-01", deadlines=[dl("paper", "2026-05-01"), dl("poster", "2026-11-01")])
    assert triggered(with_poster, TODAY, None) == []
    with_ws = ed(2026, "2026-12-01", deadlines=[dl("paper", "2026-05-01"),
                                                 dl("notification", "2026-09-01", "Workshop acceptance")])
    assert triggered(with_ws, TODAY, None) == []


def test_d_open_tba_and_e_manual():
    e = ed(2027, "2027-08-17", deadlines=[dl("paper", "2027-01-04")], source="manual")
    assert triggered(e, TODAY, {"tba": ["commitment"]}) == ["D", "E"]


def test_displayed_edition_prefers_upcoming_then_estimate_then_latest_past():
    past = ed(2026, "2026-07-06", "2026-07-11")
    est = ed(2027, source="estimated", estimated_month=7)
    assert displayed_edition([past, est], TODAY)["year"] == 2027
    assert displayed_edition([past], TODAY)["year"] == 2026


def test_combined_row_uses_member_key():
    """Review Focus 5: 결합 행의 파일 키는 구성원 이름이다."""
    assert official_key(conf("ICCV", [], group="iccv/eccv")) == "iccv"
    assert official_key(conf("ACM MM", [], group="mm")) == "mm"


def test_order_cap_and_skip():
    data = {"conferences": [
        conf("C1", [ed(2026, "2026-12-01", deadlines=[dl("paper", "2026-05-01")])]),
        conf("A1", [ed(2027, source="estimated", estimated_month=7)]),
        conf("B1", [ed(2027, "2027-06-01")]),
        conf("OK", [ed(2027, "2027-06-01", deadlines=[dl("paper", "2027-01-01")])]),
    ]}
    targets = select_targets(data, {}, TODAY, cap=2)
    assert [t["abbr"] for t in targets] == ["A1", "B1"]
    assert targets[0]["key"] == "a1" and targets[0]["criteria"] == ["A"]


def test_recently_checked_target_is_skipped():
    data = {"conferences": [conf("B1", [ed(2027, "2027-06-01")])]}
    log = {"b1/2027": {"last_checked": "2026-10-10", "results": {"B": "none"}}}
    assert select_targets(data, log, TODAY) == []
