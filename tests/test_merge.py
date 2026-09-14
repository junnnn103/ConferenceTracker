from datetime import date, datetime

from scripts.merge import (
    SOURCE_PRIORITY,
    apply_scraped,
    edition_status,
    merge_by_year,
    pick_member,
    select_editions,
)
from scripts.models import Deadline, Edition


def ed(year, source, start=None, end=None, deadlines=None, place="X"):
    return Edition(
        year=year, date_text="", start=start, end=end, place=place,
        link=None, deadlines=deadlines or [], source=source,
    )


def dl(kind, when, source="ccfddl"):
    return Deadline(kind, kind.title(), when, None, source)


def test_source_priority_order():
    assert SOURCE_PRIORITY == ("manual", "ai-deadlines", "ccfddl")


def test_higher_priority_source_wins_whole_edition():
    merged = merge_by_year({
        "ccfddl": [ed(2026, "ccfddl", place="From ccfddl")],
        "ai-deadlines": [ed(2026, "ai-deadlines", place="From HF")],
    })
    assert merged[2026].place == "From HF"
    assert merged[2026].source == "ai-deadlines"


def test_manual_beats_everything():
    merged = merge_by_year({
        "ccfddl": [ed(2026, "ccfddl", place="C")],
        "ai-deadlines": [ed(2026, "ai-deadlines", place="H")],
        "manual": [ed(2026, "manual", place="M")],
    })
    assert merged[2026].place == "M"


def test_lower_priority_fills_years_the_higher_one_lacks():
    merged = merge_by_year({
        "ccfddl": [ed(2025, "ccfddl"), ed(2026, "ccfddl")],
        "ai-deadlines": [ed(2026, "ai-deadlines")],
    })
    assert merged[2025].source == "ccfddl"
    assert merged[2026].source == "ai-deadlines"


def test_fields_are_never_mixed_across_sources():
    # HF 회차가 이겼다면 place도 deadlines도 전부 HF 것이어야 한다
    merged = merge_by_year({
        "ccfddl": [ed(2026, "ccfddl", place="C", deadlines=[dl("paper", datetime(2025, 1, 1))])],
        "ai-deadlines": [ed(2026, "ai-deadlines", place="H")],
    })
    assert merged[2026].place == "H"
    assert merged[2026].deadlines == []


def test_apply_scraped_adds_missing_track():
    base = ed(2026, "ai-deadlines", deadlines=[dl("paper", datetime(2025, 9, 11), "ai-deadlines")])
    extra = [Deadline("lbw", "LBW", datetime(2026, 2, 12), None, "cfp-scrape",
                      {"raw_text": "x", "url": "y"})]
    result = apply_scraped(base, extra)
    assert [d.type for d in result.deadlines] == ["paper", "lbw"]


def test_apply_scraped_never_overwrites_existing_track():
    base = ed(2026, "ai-deadlines", deadlines=[dl("paper", datetime(2025, 9, 11), "ai-deadlines")])
    extra = [Deadline("paper", "Paper", datetime(2025, 1, 1), None, "cfp-scrape")]
    result = apply_scraped(base, extra)
    assert len(result.deadlines) == 1
    assert result.deadlines[0].source == "ai-deadlines"


def test_apply_scraped_with_no_extra_returns_equivalent_edition():
    base = ed(2026, "ccfddl", deadlines=[dl("paper", datetime(2025, 9, 11))])
    assert apply_scraped(base, []).deadlines == base.deadlines


def test_apply_scraped_does_not_mutate_the_input_edition():
    # 같은 Edition 객체가 빌드 중 여러 곳에서 도달 가능하므로, 원본을 건드리면
    # 엉뚱한 곳에 cfp-scrape 단계가 섞인다. replace로 새 객체를 만들어야 한다.
    base = ed(2026, "ai-deadlines",
              deadlines=[dl("paper", datetime(2025, 9, 11), "ai-deadlines")])
    before = list(base.deadlines)
    extra = [Deadline("lbw", "LBW", datetime(2026, 2, 12), None, "cfp-scrape")]

    result = apply_scraped(base, extra)

    assert base.deadlines == before
    assert result is not base
    assert result.deadlines is not base.deadlines
    assert [d.type for d in result.deadlines] == ["paper", "lbw"]


def test_edition_status_upcoming_when_end_is_today_or_later():
    assert edition_status(ed(2026, "x", end=date(2026, 4, 17)), date(2026, 4, 17)) == "upcoming"
    assert edition_status(ed(2026, "x", end=date(2026, 4, 17)), date(2026, 1, 1)) == "upcoming"


def test_edition_status_past_when_ended():
    assert edition_status(ed(2026, "x", end=date(2026, 4, 17)), date(2026, 4, 18)) == "past"


def test_edition_status_unknown_without_dates():
    assert edition_status(ed(2026, "x"), date(2026, 1, 1)) == "unknown"


def test_select_editions_keeps_one_past_and_one_upcoming():
    editions = [
        ed(2024, "x", start=date(2024, 6, 1), end=date(2024, 6, 5)),
        ed(2025, "x", start=date(2025, 6, 1), end=date(2025, 6, 5)),
        ed(2026, "x", start=date(2026, 6, 1), end=date(2026, 6, 5)),
        ed(2027, "x", start=date(2027, 6, 1), end=date(2027, 6, 5)),
    ]
    picked = select_editions(editions, date(2025, 9, 8))
    assert [e.year for e in picked] == [2025, 2026]


def test_select_editions_returns_only_past_when_nothing_upcoming():
    editions = [ed(2024, "x", start=date(2024, 6, 1), end=date(2024, 6, 5))]
    assert [e.year for e in select_editions(editions, date(2026, 1, 1))] == [2024]


def test_select_editions_keeps_undated_editions_as_fallback():
    editions = [ed(2026, "x")]
    assert [e.year for e in select_editions(editions, date(2026, 1, 1))] == [2026]


def test_select_editions_on_empty_input():
    assert select_editions([], date(2026, 1, 1)) == []


def test_select_editions_keeps_undated_edition_with_future_deadline():
    # MLSys 2027: date: TBD지만 마감(2026-10-30)은 확정. 이미 끝난 2026
    # 회차(직전)와 함께 살아남아야 한다 - 날짜가 없다고 버려서 이미 끝난
    # 회차만 남기면, 확정된 마감을 무시하고 사이트에 종료된 회차만 보여주게
    # 된다.
    editions = [
        ed(2026, "x", start=date(2026, 3, 1), end=date(2026, 3, 5)),
        ed(2027, "x", deadlines=[dl("paper", datetime(2026, 10, 30))]),
    ]
    picked = select_editions(editions, date(2026, 9, 9))
    assert [e.year for e in picked] == [2026, 2027]


def test_select_editions_ignores_undated_edition_with_past_deadline():
    # 마감이 이미 지난 날짜 미상 회차는 '차기'가 아니다 - 최후의 수단으로만
    # 살아남아야 한다.
    editions = [
        ed(2026, "x", start=date(2026, 3, 1), end=date(2026, 3, 5)),
        ed(2027, "x", deadlines=[dl("paper", datetime(2025, 1, 1))]),
    ]
    picked = select_editions(editions, date(2026, 9, 9))
    assert [e.year for e in picked] == [2026]


def test_select_editions_orders_undated_deadline_candidates_by_earliest_deadline():
    # 날짜 있는 회차가 전혀 없을 때, 날짜 미상 회차 여럿 중에서는 가장 이른
    # 마감을 가진 쪽이 '차기'로 뽑힌다 — 연도가 더 최신인 쪽이 아니다.
    # (연도만으로 고르면 우연히 맞아떨어질 수 있어, 일부러 더 이른 연도가
    # 더 이른 마감을 갖도록 뒤집어 둔다.)
    editions = [
        ed(2028, "x", deadlines=[dl("paper", datetime(2026, 12, 1))]),
        ed(2027, "x", deadlines=[dl("paper", datetime(2026, 10, 30))]),
    ]
    picked = select_editions(editions, date(2026, 9, 9))
    assert [e.year for e in picked] == [2027]


def test_select_editions_all_undated_no_deadlines_falls_back_to_latest_year():
    # 날짜도 마감도 전혀 없으면 기존처럼 가장 최근 연도 하나만 남긴다.
    editions = [ed(2025, "x"), ed(2026, "x")]
    assert [e.year for e in select_editions(editions, date(2026, 1, 1))] == [2026]


def test_pick_member_chooses_earliest_upcoming():
    # ICCV는 홀수해, ECCV는 짝수해. 2026년 9월 기준 차기는 ICCV 2027.
    members = {
        "iccv": [ed(2025, "ccfddl", start=date(2025, 10, 19), end=date(2025, 10, 25)),
                 ed(2027, "ccfddl", start=date(2027, 10, 1), end=date(2027, 10, 6))],
        "eccv": [ed(2026, "ccfddl", start=date(2026, 9, 8), end=date(2026, 9, 13))],
    }
    name, editions = pick_member(members, date(2026, 9, 20))
    assert name == "iccv"
    assert [e.year for e in editions] == [2025, 2027]


def test_pick_member_prefers_the_one_actually_upcoming():
    members = {
        "iccv": [ed(2025, "ccfddl", start=date(2025, 10, 19), end=date(2025, 10, 25))],
        "eccv": [ed(2026, "ccfddl", start=date(2026, 9, 8), end=date(2026, 9, 13))],
    }
    name, _ = pick_member(members, date(2026, 1, 1))
    assert name == "eccv"


def test_pick_member_with_no_upcoming_prefers_the_most_recently_held():
    # 둘 다 차기 회차가 없을 때는 가장 최근에 열린 쪽이 대표가 되어야 한다.
    # pick_member의 -toordinal 부호가 이 비교를 뒤집는 장치다.
    members = {
        "iccv": [ed(2023, "ccfddl", start=date(2023, 10, 1), end=date(2023, 10, 6))],
        "eccv": [ed(2024, "ccfddl", start=date(2024, 9, 29), end=date(2024, 10, 4))],
    }
    name, editions = pick_member(members, date(2026, 9, 20))
    assert name == "eccv"
    assert [e.year for e in editions] == [2024]


def test_pick_member_with_no_data_returns_none():
    assert pick_member({"iccv": [], "eccv": []}, date(2026, 1, 1)) == (None, [])


def _dl(type_, label, day, source="cfp-scrape"):
    from datetime import datetime
    return Deadline(type=type_, label=label, date=datetime(2026, 10, day),
                    timezone="AoE", source=source)


def test_apply_scraped_keeps_multiple_notifications():
    """학회는 트랙마다 따로 발표하므로 notification은 여러 번 나온다.

    타입만으로 막으면, ai-deadlines가 준 라운드별 결과 발표가 이미 있다는
    이유로 워크숍 채택 발표가 통째로 버려진다 - WACV 2027에서 실제로 그랬다.
    """
    edition = Edition(
        year=2027, date_text="", start=None, end=None, place="", link=None,
        deadlines=[_dl("notification", "Round 1 Final Decisions", 9, "ai-deadlines")],
        source="ai-deadlines",
    )
    merged = apply_scraped(edition, [_dl("notification", "Workshop acceptance notification", 30)])
    labels = [d.label for d in merged.deadlines]
    assert labels == ["Round 1 Final Decisions", "Workshop acceptance notification"]


def test_apply_scraped_skips_a_duplicate_notification():
    """같은 날짜에 같은 라벨이면 같은 값이므로 중복해서 싣지 않는다."""
    existing = _dl("notification", "Round 1 Final Decisions", 9, "ai-deadlines")
    edition = Edition(
        year=2027, date_text="", start=None, end=None, place="", link=None,
        deadlines=[existing], source="ai-deadlines",
    )
    merged = apply_scraped(edition, [_dl("notification", "round 1 final decisions", 9)])
    assert len(merged.deadlines) == 1


def test_apply_scraped_still_guards_submission_tracks():
    """제출 트랙은 회차당 하나뿐이라 기존 규칙을 그대로 지킨다.

    업스트림이 준 poster 마감이 있는데 긁어온 poster가 끼어들면 어느 쪽이
    맞는지 알 수 없게 된다.
    """
    edition = Edition(
        year=2027, date_text="", start=None, end=None, place="", link=None,
        deadlines=[_dl("poster", "Posters", 9, "ai-deadlines")], source="ai-deadlines",
    )
    merged = apply_scraped(edition, [_dl("poster", "Poster Track", 30)])
    assert [d.label for d in merged.deadlines] == ["Posters"]
