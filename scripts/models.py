"""소스에 무관한 공용 데이터 모델.

모든 소스 어댑터는 외부 스키마를 이 형태로 정규화해 내놓는다.
날짜는 전부 절대 시각으로만 담는다 - D-day 같은 상대 표현은
브라우저가 계산하므로 여기서 만들지 않는다.
"""

from dataclasses import dataclass, field as dc_field
from datetime import date, datetime

# primary_deadline을 고를 때 "본 논문 마감"으로 인정하는 타입.
# 우선순위가 있는 단계별 폴백이다 - 평평한 집합이 아니다. "submission"은
# ECCV의 튜토리얼/워크숍/AI Art 제출처럼 논문과 무관한 트랙에도 쓰이므로,
# "paper" 타입이 하나라도 있으면 그것만 후보로 삼고 "submission"은 "paper"가
# 전혀 없는 학회(ICASSP, INTERSPEECH 등)에서만 대신 쓴다.
PAPER_TYPES = ("paper",)
SUBMISSION_FALLBACK_TYPES = ("submission",)

# 참고: docs/lib.js는 여기에 더해 poster/lbw/workshop 등 후발 제출 트랙까지
# 후보로 본다. 본 논문 마감이 지나도 포스터·워크숍은 몇 주 더 열려 있기
# 때문인데, 그 판단은 "오늘"에 의존하므로 빌드가 아니라 브라우저의 몫이다.
# 여기 primary_deadline은 시점과 무관한 고정값(정렬·필터의 폴백)으로 남는다.


def normalize_place(value) -> str:
    """'Bari, Italy' -> 'Bari Italy'.

    각 소스 어댑터는 place를 서로 다른 원본 스키마에서 뽑아낸다
    (ccfddl은 콤마가 섞인 자유 텍스트 한 필드, ai-deadlines는 별도의
    city/country 필드, manual은 사람이 손으로 적은 문자열). 그 추출
    방식은 스키마마다 다르므로 각 어댑터가 계속 맡는다. 하지만 콤마를
    없애 표기를 통일하는 것은 스키마와 무관한 "표시 방식"의 문제라,
    여기 Edition 생성 지점 한 곳에만 두고 모든 소스가 자동으로 같은
    규칙을 받게 한다 - 안 그러면 새 소스가 추가될 때마다 이 함수를
    복사해 붙이는 걸 잊을 수 있다(실제로 manual.py가 그랬다: ccfddl.py에만
    있던 이 로직이 manual 항목에는 적용되지 않아, HRI/IJCAI/RSS의
    manual 항목만 콤마가 남은 채로 다른 35개 행과 다르게 표시됐다).
    """
    if not value or str(value).strip().upper() in {"TBD", "TBA"}:
        return ""
    return " ".join(str(value).replace(",", " ").split())


@dataclass
class Deadline:
    type: str
    label: str
    date: datetime
    timezone: str | None
    source: str
    evidence: dict | None = None

    def to_dict(self) -> dict:
        out = {
            "type": self.type,
            "label": self.label,
            "date": self.date.isoformat(),
            "source": self.source,
        }
        if self.timezone:
            out["timezone"] = self.timezone
        if self.evidence:
            out["evidence"] = self.evidence
        return out


@dataclass
class Edition:
    year: int
    date_text: str
    start: date | None
    end: date | None
    place: str
    link: str | None
    deadlines: list[Deadline]
    source: str
    # 확정 개최일이 없을 때 "예년 기준 이 달쯤"을 나타낸다(1-12). 추정값이므로
    # start/end와 달리 화면에 "(미정)"을 달아 보여준다. scripts/estimate.py 참고.
    estimated_month: int | None = None

    def __post_init__(self) -> None:
        self.place = normalize_place(self.place)

    def primary_deadline(self) -> datetime | None:
        """본 논문 마감. paper 타입을 최우선으로, 없으면 submission 타입을,
        그마저 없으면 가장 늦은 마감으로 대체한다."""
        if not self.deadlines:
            return None
        papers = [d for d in self.deadlines if d.type in PAPER_TYPES]
        if papers:
            return max(d.date for d in papers)
        submissions = [d for d in self.deadlines if d.type in SUBMISSION_FALLBACK_TYPES]
        if submissions:
            return max(d.date for d in submissions)
        return max(d.date for d in self.deadlines)

    def to_dict(self) -> dict:
        primary = self.primary_deadline()
        out = {
            "year": self.year,
            "date_text": self.date_text,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "place": self.place,
            "link": self.link,
            "deadlines": [d.to_dict() for d in self.deadlines],
            "primary_deadline": primary.isoformat() if primary else None,
            "source": self.source,
        }
        if self.estimated_month is not None:
            out["estimated_month"] = self.estimated_month
        return out


@dataclass
class Conference:
    abbr: str
    abbr_group: str
    full_name: str
    grade: str
    ai_specialist: bool
    field: str
    homepage: str | None
    bk_grade: str | None = None
    editions: list[Edition] = dc_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "abbr": self.abbr,
            "abbr_group": self.abbr_group,
            "full_name": self.full_name,
            "grade": self.grade,
            "bk_grade": self.bk_grade,
            "ai_specialist": self.ai_specialist,
            "field": self.field,
            "homepage": self.homepage,
            "editions": [e.to_dict() for e in self.editions],
        }
