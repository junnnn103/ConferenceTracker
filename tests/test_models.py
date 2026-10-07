from datetime import date, datetime

from scripts.models import Conference, Deadline, Edition


def test_deadline_holds_absolute_time_only():
    d = Deadline(
        type="paper",
        label="Paper",
        date=datetime(2025, 11, 13, 23, 59, 59),
        timezone="AoE",
        source="ai-deadlines",
    )
    assert d.evidence is None
    assert d.to_dict() == {
        "type": "paper",
        "label": "Paper",
        "date": "2025-11-13T23:59:59",
        "timezone": "AoE",
        "source": "ai-deadlines",
    }


def test_deadline_with_evidence_serializes_it():
    d = Deadline(
        type="poster",
        label="Posters",
        date=datetime(2026, 4, 21, 22, 0, 0),
        timezone=None,
        source="cfp-scrape",
        evidence={"raw_text": "Posters deadline: April 21, 2026", "url": "https://x/"},
    )
    assert d.to_dict()["evidence"]["url"] == "https://x/"
    assert "timezone" not in d.to_dict()


def test_edition_primary_deadline_prefers_paper():
    ed = Edition(
        year=2026,
        date_text="June 3-7, 2026",
        start=date(2026, 6, 3),
        end=date(2026, 6, 7),
        place="Denver USA",
        link=None,
        source="ai-deadlines",
        deadlines=[
            Deadline("abstract", "Abstract", datetime(2025, 11, 7), None, "ai-deadlines"),
            Deadline("paper", "Paper", datetime(2025, 11, 13), None, "ai-deadlines"),
            Deadline("notification", "Notify", datetime(2026, 2, 20), None, "ai-deadlines"),
        ],
    )
    assert ed.primary_deadline() == datetime(2025, 11, 13)


def test_edition_primary_deadline_falls_back_to_latest_when_no_paper():
    # paper 계열 단계가 하나도 없을 때만 최댓값 대체가 동작해야 한다
    ed = Edition(
        year=2026, date_text="", start=None, end=None, place="", link=None,
        source="ccfddl",
        deadlines=[
            Deadline("abstract", "Abstract", datetime(2025, 9, 4), None, "ccfddl"),
            Deadline("notification", "Notify", datetime(2026, 1, 20), None, "ccfddl"),
        ],
    )
    assert ed.primary_deadline() == datetime(2026, 1, 20)


def test_edition_primary_deadline_prefers_paper_over_unrelated_submission():
    # ECCV처럼 "submission" 타입이 튜토리얼/워크숍/AI Art 같은 논문과 무관한
    # 트랙에도 쓰이는 경우, "paper" 타입이 있으면 그것만 후보여야 한다.
    # submission 타입 중 가장 늦은 것(AI Art, 6월)이 이겨서는 안 된다.
    ed = Edition(
        year=2026, date_text="", start=None, end=None, place="", link=None,
        source="ccfddl",
        deadlines=[
            Deadline("submission", "Tutorial Proposal Submission", datetime(2026, 2, 15), None, "ccfddl"),
            Deadline("paper", "Paper Submission", datetime(2026, 3, 5), None, "ccfddl"),
            Deadline("submission", "AI Art Submission", datetime(2026, 6, 14), None, "ccfddl"),
        ],
    )
    assert ed.primary_deadline() == datetime(2026, 3, 5)


def test_edition_primary_deadline_treats_submission_as_paper():
    ed = Edition(
        year=2026, date_text="", start=None, end=None, place="", link=None,
        source="ccfddl",
        deadlines=[
            Deadline("submission", "Submission", datetime(2025, 9, 11), None, "ccfddl"),
            Deadline("notification", "Notify", datetime(2026, 1, 20), None, "ccfddl"),
        ],
    )
    assert ed.primary_deadline() == datetime(2025, 9, 11)


def test_edition_primary_deadline_is_none_when_no_deadlines():
    ed = Edition(2026, "", None, None, "", None, [], "ccfddl")
    assert ed.primary_deadline() is None


def test_conference_serializes_nested_editions():
    conf = Conference(
        abbr="CVPR", abbr_group="cvpr",
        full_name="Computer Vision and Pattern Recognition",
        grade="최우수", ai_specialist=True, field="CV",
        homepage="https://cvpr.thecvf.com/",
        editions=[Edition(2026, "June 3-7, 2026", date(2026, 6, 3), date(2026, 6, 7),
                          "Denver USA", None, [], "ai-deadlines")],
    )
    out = conf.to_dict()
    assert out["abbr"] == "CVPR"
    assert out["editions"][0]["start"] == "2026-06-03"
    assert out["editions"][0]["primary_deadline"] is None


def test_conference_bk_grade_defaults_to_none_and_serializes():
    # bk_grade를 넘기지 않는 기존 호출부(테스트 픽스처 포함)가 깨지지 않아야
    # 하므로 기본값이 있어야 한다. 동시에 to_dict가 필드를 항상 내보내야
    # BK 목록에 없는 학회("null")와 아직 채워지지 않은 상태를 프론트에서
    # 구분할 수 있다.
    conf = Conference(
        abbr="ICIP", abbr_group="icip", full_name="Image Processing",
        grade="우수", ai_specialist=True, field="CV", homepage="https://example.org/",
    )
    assert conf.bk_grade is None
    assert conf.to_dict()["bk_grade"] is None


def test_conference_bk_grade_serializes_when_set():
    conf = Conference(
        abbr="CVPR", abbr_group="cvpr", full_name="Computer Vision",
        grade="최우수", ai_specialist=True, field="CV", homepage="https://example.org/",
        bk_grade="S",
    )
    assert conf.to_dict()["bk_grade"] == "S"


def _edition_with(*deadlines):
    return Edition(2027, "", None, None, "", None, list(deadlines), "ccfddl")


def test_commitment_counts_as_main_paper():
    """ARR 학회는 commitment가 그 학회에 내는 실제 마감이다.

    paper만 본 논문으로 치면 ACL 2027처럼 ARR 마감(1/4)이 지난 뒤
    commitment 마감이 올라와도 대표 마감이 되지 못한다.
    """
    ed = _edition_with(
        Deadline("paper", "ARR", datetime(2027, 1, 4, 23, 59, 59), "AoE", "ccfddl"),
        Deadline("commitment", "Commitment", datetime(2027, 3, 1, 23, 59, 59), "AoE", "official"),
        Deadline("poster", "Posters", datetime(2027, 4, 1, 23, 59, 59), "AoE", "cfp-scrape"),
    )
    assert ed.primary_deadline() == datetime(2027, 3, 1, 23, 59, 59)


def test_commitment_deadline_and_short_paper_count_too():
    """ai-deadlines는 commitment_deadline이라는 이름을 쓴다."""
    ed = _edition_with(
        Deadline("commitment_deadline", "ARR commitment deadline", datetime(2026, 3, 14), "AoE", "ai-deadlines"),
        Deadline("short_paper", "Short papers", datetime(2026, 2, 1), "AoE", "official"),
        Deadline("submission", "Tutorial proposals", datetime(2026, 5, 1), None, "ai-deadlines"),
    )
    assert ed.primary_deadline() == datetime(2026, 3, 14)
