"""확정 일정이 없는 회차에 붙이는 예년 기준 추정."""

from datetime import date

from scripts.build import _fill_estimates
from scripts.estimate import (
    next_year_after,
    period_years,
    placeholder_edition,
    typical_month,
)
from scripts.models import Deadline, Edition


def ed(year, month=None, day=1, *, place="", deadlines=None, source="ccfddl"):
    start = date(year, month, day) if month else None
    return Edition(
        year=year,
        date_text=f"{year}" if month else "",
        start=start,
        end=start,
        place=place,
        link=None,
        deadlines=deadlines or [],
        source=source,
    )


def test_typical_month_uses_the_most_common_month():
    assert typical_month([ed(2024, 7), ed(2025, 7), ed(2026, 6)]) == 7


def test_typical_month_breaks_ties_with_the_latest_edition():
    # 학회가 시기를 옮겼다면 옛날보다 최근 쪽이 다음 회차에 가깝다.
    assert typical_month([ed(2024, 6), ed(2026, 9)]) == 9


def test_typical_month_is_none_without_any_dated_edition():
    assert typical_month([ed(2027)]) is None
    assert typical_month([]) is None


def test_period_years_defaults_to_one_for_a_single_edition():
    assert period_years([ed(2026, 7)]) == 1


def test_period_years_detects_a_biennial_cadence():
    assert period_years([ed(2022, 9), ed(2024, 9), ed(2026, 9)]) == 2


def test_next_year_after_skips_years_already_past():
    # 2019년까지만 있는 학회를 2027년에 "2020년 개최 예정"이라고 내놓으면 안 된다.
    assert next_year_after([ed(2019, 7)], date(2026, 9, 14)) is None
    assert next_year_after([ed(2026, 7)], date(2026, 9, 14)) == 2027


def test_placeholder_carries_only_a_month_and_year():
    """추정 회차는 확정 일정처럼 보일 만한 값을 하나도 갖지 않는다."""
    placeholder = placeholder_edition([ed(2026, 7, 6, place="Seoul")], date(2026, 9, 14))
    assert placeholder.year == 2027
    assert placeholder.estimated_month == 7
    assert placeholder.start is None and placeholder.end is None
    assert placeholder.place == ""
    assert placeholder.link is None
    assert placeholder.date_text == ""
    # 마감이 있으면 있지도 않은 D-day가 뜬다.
    assert placeholder.deadlines == []
    assert placeholder.source == "estimated"


def test_placeholder_is_none_without_dated_history():
    assert placeholder_edition([ed(2027)], date(2026, 9, 14)) is None


def test_fill_estimates_adds_a_next_edition_when_everything_has_passed():
    editions = [ed(2026, 7, 6)]
    selected = list(editions)
    note = _fill_estimates(selected, editions, date(2026, 9, 14), combined=False)
    assert note == {"year": 2027, "month": 7, "kind": "차기 회차 미공개"}
    assert [e.year for e in selected] == [2026, 2027]


def test_fill_estimates_skips_combined_rows():
    """ECCV 2026 다음은 ECCV 2028이 아니라 ICCV 2027이다.

    결합 행은 다음 차례가 구성원끼리 번갈아 오므로 연도도 이름도 여기서
    정할 수 없다. 자리표시자를 만들면 틀린 이름표가 붙는다.
    """
    editions = [ed(2024, 9), ed(2026, 9)]
    selected = list(editions)
    assert _fill_estimates(selected, editions, date(2026, 10, 1), combined=True) is None
    assert len(selected) == 2


def test_fill_estimates_leaves_confirmed_dates_alone():
    """소스가 준 개최일이 있으면 추정은 끼어들지 않는다."""
    editions = [ed(2026, 7), ed(2027, 7)]
    selected = list(editions)
    assert _fill_estimates(selected, editions, date(2026, 9, 14), combined=False) is None
    assert all(e.estimated_month is None for e in selected)


def test_fill_estimates_fills_a_month_on_an_undated_edition():
    """MLSys 2027처럼 회차는 있는데 개최일만 없는 경우."""
    deadline = Deadline(
        type="paper", label="Paper",
        date=__import__("datetime").datetime(2026, 10, 30), timezone="UTC", source="ccfddl",
    )
    editions = [ed(2026, 5, 17), ed(2027, deadlines=[deadline])]
    selected = list(editions)
    note = _fill_estimates(selected, editions, date(2026, 9, 14), combined=False)
    assert note == {"year": 2027, "month": 5, "kind": "개최일 미정"}
    assert selected[1].estimated_month == 5
    # 이미 있던 마감은 그대로 남는다.
    assert selected[1].deadlines == [deadline]
    # 자리표시자를 덧붙이지 않는다.
    assert len(selected) == 2
