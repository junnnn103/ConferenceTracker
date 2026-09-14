"""확정 일정이 없는 회차에 '예년 기준 이 달쯤'이라는 추정을 붙인다.

두 가지 경우를 다룬다.

1. 회차는 있는데 개최일이 없는 경우 (MLSys 2027처럼 ccfddl이 date: TBD를 준다)
2. 마지막 회차가 이미 지났고 다음 회차 정보가 아직 어디에도 없는 경우
   (ICML 2026이 끝났는데 2027이 아직 안 올라온 상태)

두 경우 모두 과거 회차의 개최 월을 그대로 옮겨 "July, 2027 (미정)"처럼
보여준다. 추정값은 반드시 estimated_month로만 싣고 start/end/place는 비워
둔다 - 확정 일정처럼 보이면 안 되고, 다음 주 월요일 갱신 때 진짜 값이
올라오면 그쪽이 이긴다.

결합 행(iccv/eccv, asru/slt)은 2번을 하지 않는다. 다음 차례가 구성원끼리
번갈아 오므로 - ECCV 2026 다음은 ECCV 2028이 아니라 ICCV 2027이다 - 연도도
이름도 여기서 정할 수 없기 때문이다.
"""

from collections import Counter
from datetime import date

from scripts.models import Edition

# 과거 회차가 하나뿐이면 주기를 알 수 없다. 이 표의 비결합 학회는 전부
# 매년 열리므로 1년으로 본다.
DEFAULT_PERIOD_YEARS = 1


def typical_month(editions: list[Edition]) -> int | None:
    """과거 회차들이 주로 열린 달. 개최일이 있는 회차가 없으면 None.

    동률이면 가장 최근 회차의 달을 쓴다 - 학회가 시기를 옮겼다면 옛날보다
    최근 쪽이 다음 회차에 가깝다.
    """
    dated = [e for e in editions if e.start]
    if not dated:
        return None
    counts = Counter(e.start.month for e in dated)
    best = max(counts.values())
    tied = {m for m, n in counts.items() if n == best}
    if len(tied) == 1:
        return next(iter(tied))
    latest = max(dated, key=lambda e: (e.year, e.start))
    return latest.start.month if latest.start.month in tied else sorted(tied)[0]


def period_years(editions: list[Edition]) -> int:
    """연속한 회차 사이의 간격. 회차가 하나뿐이면 1년으로 본다."""
    years = sorted({e.year for e in editions if e.start})
    if len(years) < 2:
        return DEFAULT_PERIOD_YEARS
    gaps = [b - a for a, b in zip(years, years[1:])]
    return Counter(gaps).most_common(1)[0][0] or DEFAULT_PERIOD_YEARS


def next_year_after(editions: list[Edition], today: date) -> int | None:
    """다음 회차의 연도. 추정할 근거가 없으면 None."""
    years = [e.year for e in editions]
    if not years:
        return None
    nxt = max(years) + period_years(editions)
    # 이미 지난 연도를 다음 회차라고 내놓지 않는다.
    return nxt if nxt >= today.year else None


def placeholder_edition(editions: list[Edition], today: date) -> Edition | None:
    """다음 회차 자리표시자. 월과 연도만 있고 나머지는 비어 있다."""
    month = typical_month(editions)
    year = next_year_after(editions, today)
    if month is None or year is None:
        return None
    return Edition(
        year=year,
        date_text="",
        start=None,
        end=None,
        place="",
        link=None,
        deadlines=[],
        source="estimated",
        estimated_month=month,
    )
