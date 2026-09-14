"""소스 병합, 결합 행 해소, 회차 선택.

병합은 회차(연도) 단위로 소스를 통째 고른다. 필드 단위로 섞지 않는
이유는, 값이 어긋났을 때 어느 값이 어디서 왔는지 추적할 수 없게 되기
때문이다. cfp-scrape만 예외로 상위 소스가 갖지 않은 단계를 채운다.
"""

from dataclasses import replace
from datetime import date

from scripts.models import Deadline, Edition

# 앞에 올수록 우선한다.
SOURCE_PRIORITY = ("manual", "ai-deadlines", "ccfddl")


def merge_by_year(by_source: dict[str, list[Edition]]) -> dict[int, Edition]:
    """연도별로 가장 높은 우선순위 소스의 회차를 통째로 고른다."""
    merged: dict[int, Edition] = {}
    # 우선순위 역순으로 덮어써서 결국 최상위가 남게 한다.
    for source in reversed(SOURCE_PRIORITY):
        for edition in by_source.get(source) or []:
            merged[edition.year] = edition
    return merged


# 한 회차에 여러 번 나오는 것이 정상인 타입. 학회는 트랙마다 따로 발표를
# 하므로(본 논문 라운드, 워크숍 채택, 튜토리얼 채택) notification은 타입이
# 이미 있다는 이유로 막으면 안 된다. 제출 트랙(poster, tutorial 등)은
# 회차당 하나뿐이라 기존 규칙을 그대로 둔다.
MULTI_INSTANCE_TYPES = frozenset({"notification"})


def apply_scraped(edition: Edition, extra: list[Deadline]) -> Edition:
    """CFP에서 추출한 단계를 채운다.

    제출 트랙은 이미 있는 타입을 절대 건드리지 않는다 - 업스트림이 준
    poster 마감이 있는데 긁어온 poster가 끼어들면 어느 쪽이 맞는지 알 수
    없게 된다.

    notification처럼 원래 여러 번 나오는 타입은 타입만으로 막을 수 없다.
    WACV 2027은 ai-deadlines가 준 라운드별 결과 발표를 이미 갖고 있어서,
    워크숍 채택 발표 세 건이 통째로 버려졌다. 이런 타입은 같은 날짜에 같은
    라벨이 이미 있을 때만 건너뛴다.
    """
    if not extra:
        return edition
    existing_types = {d.type for d in edition.deadlines}
    existing_keys = {
        (d.type, d.date, (d.label or "").strip().lower()) for d in edition.deadlines
    }
    additions = []
    for d in extra:
        if d.type in MULTI_INSTANCE_TYPES:
            if (d.type, d.date, (d.label or "").strip().lower()) not in existing_keys:
                additions.append(d)
        elif d.type not in existing_types:
            additions.append(d)
    if not additions:
        return edition
    return replace(edition, deadlines=[*edition.deadlines, *additions])


def edition_status(edition: Edition, today: date) -> str:
    """upcoming / past / unknown.

    날짜만 본다 - 마감이 있어도 "unknown"을 "upcoming"으로 바꾸지 않는다.
    pick_member도 이 함수로 결합 행(ICCV/ECCV 등)의 대표를 고르는데,
    거기서 마감 유무까지 승격 기준에 넣으면 날짜 없이 마감만 있는 구성원이
    실제 개최일이 확정된 다른 구성원을 제치고 대표가 될 수 있다 - 이 함수의
    책임 밖이다. 날짜 없는 회차를 마감으로 구제하는 로직은 그 필요가 실제로
    있는 select_editions에만 있다(_future_deadline).
    """
    end = edition.end or edition.start
    if end is None:
        return "unknown"
    return "upcoming" if end >= today else "past"


def _future_deadline(edition: Edition, today: date) -> date | None:
    """날짜 정보가 없는 회차를 위한 대체 신호.

    학회는 개최지/일정보다 마감을 먼저 공지하는 경우가 흔하다(예: MLSys
    2027은 날짜는 TBD지만 마감은 확정되어 있다). 아직 지나지 않은 마감이
    있다면 그 날짜를 돌려주고, 없으면 None을 돌려준다.
    """
    primary = edition.primary_deadline()
    if primary is None:
        return None
    primary_date = primary.date() if hasattr(primary, "date") else primary
    return primary_date if primary_date >= today else None


def select_editions(editions: list[Edition], today: date) -> list[Edition]:
    """직전 1개와 차기 1개만 남긴다.

    브라우저가 날짜 경계를 넘어가도 올바른 회차를 고를 수 있도록 둘을 넘긴다.

    날짜가 없어도 아직 지나지 않은 마감이 있는 회차는 '차기'로 인정한다 —
    날짜 없이 버리면 확정된 마감을 무시하고 이미 끝난 이전 회차만 보여주게
    되기 때문이다. 날짜도 마감도 전혀 없는 회차는 여전히 다른 후보가 전혀
    없을 때만 최후의 수단으로 살린다.
    """
    if not editions:
        return []

    dated = [e for e in editions if (e.end or e.start) is not None]
    # 날짜는 없지만 아직 지나지 않은 마감이 있는 회차. (date, edition) 쌍으로
    # 들고 있다가 날짜 기반 후보와 마감일을 기준으로 함께 정렬한다.
    undated_with_deadline = [
        (deadline, e)
        for e in editions
        if (e.end or e.start) is None
        and (deadline := _future_deadline(e, today)) is not None
    ]

    if not dated and not undated_with_deadline:
        # 전부 날짜도 마감도 미상이면 가장 최근 연도 하나만 남겨 '일정
        # 미확인'으로 보낸다.
        return [max(editions, key=lambda e: e.year)]

    upcoming = sorted(
        [(e.start or e.end, e) for e in dated if edition_status(e, today) == "upcoming"]
        + undated_with_deadline,
        key=lambda pair: pair[0],
    )
    past = sorted(
        (e for e in dated if edition_status(e, today) == "past"),
        key=lambda e: (e.start or e.end),
    )

    picked = []
    if past:
        picked.append(past[-1])
    if upcoming:
        picked.append(upcoming[0][1])
    if not picked:
        return [max(editions, key=lambda e: e.year)]
    return picked


def pick_member(
    members: dict[str, list[Edition]], today: date
) -> tuple[str | None, list[Edition]]:
    """결합 행에서 대표 학회를 고른다.

    ICCV/ECCV, ASRU/SLT처럼 격년으로 번갈아 열리는 쌍이 대상이다.
    차기 회차가 더 이른 쪽을 대표로 삼고, 차기가 없으면 가장 최근에
    열린 쪽을 쓴다.
    """
    best_name: str | None = None
    best_key = None

    for name, editions in members.items():
        if not editions:
            continue
        upcoming = [e for e in editions if edition_status(e, today) == "upcoming"]
        if upcoming:
            # 차기가 있는 쪽이 무조건 우선. 그중 가장 이른 것.
            key = (0, min((e.start or e.end) for e in upcoming))
        else:
            dated = [e for e in editions if (e.end or e.start) is not None]
            if dated:
                # 차기가 없으면 가장 최근에 끝난 쪽. 최신일수록 앞서도록 부호를 뒤집는다.
                key = (1, -max((e.end or e.start) for e in dated).toordinal())
            else:
                key = (2, 0)
        if best_key is None or key < best_key:
            best_key, best_name = key, name

    if best_name is None:
        return None, []
    return best_name, members[best_name]
