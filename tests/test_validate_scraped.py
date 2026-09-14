from datetime import date
import json
import sys

import pytest

from scripts import validate_scraped
from scripts.validate_scraped import normalize_whitespace, validate_extraction

PAGE = """
CHI 2026 Call for Participation

Late-Breaking Work submission deadline: February 12, 2026
Workshop proposals are due October 15, 2025
"""

START = date(2026, 4, 13)
TODAY = date(2025, 9, 8)


def item(**kw):
    base = {
        "type": "lbw",
        "label": "Late-Breaking Work",
        "date": "2026-02-12 23:59:59",
        "confidence": "high",
        "raw_text": "Late-Breaking Work submission deadline: February 12, 2026",
        "url": "https://chi2026.acm.org/lbw/",
    }
    base.update(kw)
    return base


def test_accepts_item_whose_raw_text_appears_in_page():
    accepted, rejected = validate_extraction([item()], PAGE, START, TODAY)
    assert len(accepted) == 1
    assert rejected == []
    assert accepted[0]["evidence"]["raw_text"].startswith("Late-Breaking Work")
    assert accepted[0]["evidence"]["url"] == "https://chi2026.acm.org/lbw/"
    assert "confidence" not in accepted[0]


def test_rejects_fabricated_raw_text():
    # 모델이 문장을 지어낸 경우 - 가장 중요한 방어선
    bad = item(raw_text="Poster deadline: March 3, 2026", type="poster")
    accepted, rejected = validate_extraction([bad], PAGE, START, TODAY)
    assert accepted == []
    assert rejected[0]["reject_reason"] == "raw_text_not_in_page"


def test_raw_text_match_ignores_whitespace_differences():
    spaced = item(raw_text="Late-Breaking   Work submission deadline:\n February 12, 2026")
    accepted, _ = validate_extraction([spaced], PAGE, START, TODAY)
    assert len(accepted) == 1


def test_rejects_deadline_after_conference_start():
    late = item(date="2026-05-01 23:59:59")
    accepted, rejected = validate_extraction([late], PAGE, START, TODAY)
    assert accepted == []
    assert rejected[0]["reject_reason"] == "deadline_after_conference"


def test_rejects_deadline_more_than_18_months_before_conference():
    ancient = item(date="2024-01-01 23:59:59")
    accepted, rejected = validate_extraction([ancient], PAGE, START, TODAY)
    assert accepted == []
    assert rejected[0]["reject_reason"] == "deadline_too_early"


def test_rejects_low_confidence():
    unsure = item(confidence="low")
    accepted, rejected = validate_extraction([unsure], PAGE, START, TODAY)
    assert accepted == []
    assert rejected[0]["reject_reason"] == "low_confidence"


def test_rejects_unparseable_date():
    broken = item(date="sometime in spring")
    accepted, rejected = validate_extraction([broken], PAGE, START, TODAY)
    assert accepted == []
    assert rejected[0]["reject_reason"] == "unparseable_date"


def test_rejects_missing_raw_text():
    empty = item(raw_text="")
    accepted, rejected = validate_extraction([empty], PAGE, START, TODAY)
    assert accepted == []
    assert rejected[0]["reject_reason"] == "raw_text_not_in_page"


def test_rejects_unknown_track():
    weird = item(type="keynote")
    accepted, rejected = validate_extraction([weird], PAGE, START, TODAY)
    assert accepted == []
    assert rejected[0]["reject_reason"] == "unknown_track"


def test_date_range_check_is_skipped_when_conference_start_unknown():
    accepted, rejected = validate_extraction([item()], PAGE, None, TODAY)
    assert len(accepted) == 1


def test_processes_every_item_independently():
    good = item()
    bad = item(raw_text="invented text", type="poster")
    accepted, rejected = validate_extraction([good, bad], PAGE, START, TODAY)
    assert len(accepted) == 1
    assert len(rejected) == 1


def test_normalize_whitespace_collapses_runs():
    assert normalize_whitespace("a  b\n\tc ") == "a b c"


def test_rejects_real_sentence_that_does_not_mention_the_claimed_date():
    # 페이지에 실재하는 문장이라도 주장된 날짜를 언급하지 않으면 대조가 아니다.
    # 이것이 없으면 아무 문장이나 날조된 날짜를 뒷받침한다.
    unrelated = item(raw_text="Workshop proposals are due October 15, 2025",
                     date="2026-03-03 23:59:59")
    accepted, rejected = validate_extraction([unrelated], PAGE, START, TODAY)
    assert accepted == []
    assert rejected[0]["reject_reason"] == "date_not_in_raw_text"


def test_accepts_iso_date_written_in_raw_text():
    page = "Poster deadline is 2026-02-12 for all submissions."
    iso = item(type="poster", raw_text="Poster deadline is 2026-02-12 for all submissions.",
               date="2026-02-12 23:59:59")
    accepted, _ = validate_extraction([iso], page, START, TODAY)
    assert len(accepted) == 1


def test_accepts_day_before_month_in_raw_text():
    page = "Posters are due 12 February and cannot be extended."
    dayfirst = item(type="poster", raw_text="Posters are due 12 February and cannot be extended.",
                    date="2026-02-12 23:59:59")
    accepted, _ = validate_extraction([dayfirst], page, START, TODAY)
    assert len(accepted) == 1


def test_year_or_id_digits_adjacent_to_a_month_do_not_corroborate():
    # "2012 February"의 12는 연도 꼬리이지 일자가 아니다. 단어 경계가 없으면
    # 페이지에 실재하는 아무 문장이나 2월 12일을 뒷받침하게 된다.
    page = "The conference series started in 2012 February in Boston."
    spurious = item(
        type="poster",
        raw_text="The conference series started in 2012 February in Boston.",
        date="2026-02-12 23:59:59",
    )
    accepted, rejected = validate_extraction([spurious], page, START, TODAY)
    assert accepted == []
    assert rejected[0]["reject_reason"] == "date_not_in_raw_text"


def test_existing_yaml_is_kept_when_no_items_pass(tmp_path, monkeypatch):
    """기존 YAML이 있고 이번 실행에서 검증할 항목이 없으면 파일을 유지한다.

    transient failure가 기존 데이터를 지우지 않도록 한다.
    """
    scraped_dir = tmp_path / "scraped"
    scraped_dir.mkdir()
    raw_dir = scraped_dir / "raw"
    raw_dir.mkdir()

    # 기존 YAML 파일 생성
    existing_yaml = scraped_dir / "chi.yaml"
    existing_yaml.write_text("abbr: chi\neditions:\n  - year: 2025\n", encoding="utf-8")

    # 현재 실행에서 검증할 수 없는 JSON (모든 항목이 탈락할 raw_text)
    raw_json = raw_dir / "chi.json"
    raw_json.write_text(
        json.dumps({
            "abbr": "chi",
            "editions": [{
                "year": 2026,
                "conference_start": "2026-04-13",
                "items": [{
                    "type": "lbw",
                    "label": "LBW",
                    "date": "2026-02-12 23:59:59",
                    "confidence": "high",
                    "raw_text": "fabricated text",
                    "url": "http://example.com",
                }],
            }],
        }),
        encoding="utf-8",
    )

    # page.txt 파일이 없어서 page_text_missing이 될 것
    monkeypatch.setattr(validate_scraped, "SCRAPED_DIR", scraped_dir)
    monkeypatch.setattr(sys, "argv", ["validate_scraped.py"])

    exit_code = validate_scraped.main()

    # 기존 YAML이 여전히 존재해야 함
    assert existing_yaml.exists()
    assert existing_yaml.read_text(encoding="utf-8").startswith("abbr: chi")


def test_one_malformed_json_does_not_stop_next_file(tmp_path, monkeypatch):
    """한 파일이 손상되어도 다음 파일은 처리된다."""
    scraped_dir = tmp_path / "scraped"
    scraped_dir.mkdir()
    raw_dir = scraped_dir / "raw"
    raw_dir.mkdir()

    # 첫 번째 파일: conference_start가 잘못된 형식
    bad_json = raw_dir / "aaa_bad.json"
    bad_json.write_text(
        json.dumps({
            "abbr": "bad",
            "editions": [{
                "year": 2026,
                "conference_start": "not-a-date",  # 잘못된 형식
                "items": [],
            }],
        }),
        encoding="utf-8",
    )

    # 두 번째 파일: 정상적인 파일
    good_json = raw_dir / "zzz_good.json"
    page_text = "Poster deadline is 2026-02-12."
    good_json.write_text(
        json.dumps({
            "abbr": "good",
            "editions": [{
                "year": 2026,
                "conference_start": "2026-04-13",
                "items": [{
                    "type": "poster",
                    "label": "Poster",
                    "date": "2026-02-12 23:59:59",
                    "confidence": "high",
                    "raw_text": "Poster deadline is 2026-02-12",
                    "url": "http://example.com",
                }],
            }],
        }),
        encoding="utf-8",
    )
    (raw_dir / "zzz_good.txt").write_text(page_text, encoding="utf-8")

    monkeypatch.setattr(validate_scraped, "SCRAPED_DIR", scraped_dir)
    monkeypatch.setattr(sys, "argv", ["validate_scraped.py"])

    exit_code = validate_scraped.main()

    # 좋은 파일의 YAML이 생성되어야 함
    good_yaml = scraped_dir / "zzz_good.yaml"
    assert good_yaml.exists()
    content = good_yaml.read_text(encoding="utf-8")
    assert "abbr: good" in content
    assert "2026-02-12" in content


def test_workshop_notification_passes_the_track_gate():
    """워크숍 채택 발표가 게이트를 통과해야 한다.

    워크숍 제안 마감은 워크숍을 열려는 위원회가 내는 것이라 참가자에게는
    쓸모가 없고, 정작 의미 있는 날은 어떤 워크숍이 채택됐는지 알려주는
    발표일이다. notification이 KNOWN_TRACKS에 없으면 이 값이 들어올 길이
    없어 docs/lib.js의 workshopNotifications 규칙이 작동하지 못한다.
    """
    page = "Workshop acceptance notification: August 15, 2026"
    accepted, rejected = validate_extraction(
        [{
            "type": "notification",
            "label": "Workshop acceptance notification",
            "date": "2026-08-15 23:59:59",
            "confidence": "high",
            "raw_text": page,
            "url": "https://wacv.thecvf.com/Conferences/2027/CallForWorkshops",
        }],
        page,
        date(2027, 1, 4),
        date(2026, 9, 14),
    )
    assert rejected == []
    assert accepted[0]["type"] == "notification"
    assert accepted[0]["label"] == "Workshop acceptance notification"


def test_notification_still_needs_its_date_in_the_page():
    """타입을 늘려도 나머지 게이트는 그대로다."""
    page = "Workshop acceptance notification: August 15, 2026"
    accepted, rejected = validate_extraction(
        [{
            "type": "notification",
            "label": "Workshop acceptance notification",
            "date": "2026-11-20 23:59:59",
            "confidence": "high",
            "raw_text": page,
            "url": "https://example.com",
        }],
        page,
        date(2027, 1, 4),
        date(2026, 9, 14),
    )
    assert accepted == []
    assert rejected[0]["reject_reason"] == "date_not_in_raw_text"


def test_only_the_four_tracked_tracks_pass():
    """추적하는 트랙은 워크숍/풀페이퍼/숏페이퍼(LBW)/포스터 넷뿐이다.

    쓰지 않는 트랙을 받아 두면 대표 마감 자리를 차지한다 - WACV 2027에서
    튜토리얼 제안 마감이 워크숍 일정을 밀어내고 대표로 떴다.
    """
    page = "Submission deadline: October 4, 2026"
    def run(track):
        return validate_extraction(
            [{"type": track, "label": track, "date": "2026-10-04 23:59:59",
              "confidence": "high", "raw_text": page, "url": "https://example.com"}],
            page, date(2027, 1, 4), date(2026, 9, 14),
        )
    for track in ("poster", "lbw", "workshop", "notification"):
        accepted, rejected = run(track)
        assert rejected == [], f"{track}은 통과해야 한다"
    for track in ("tutorial", "demo", "doctoral_consortium", "other"):
        accepted, rejected = run(track)
        assert accepted == [], f"{track}은 막혀야 한다"
        assert rejected[0]["reject_reason"] == "unknown_track"


def test_timezone_is_carried_when_the_page_declares_it():
    """AoE 마감은 KST로 하루 뒤다. 시간대를 버리면 하루 이른 날짜가 뜬다.

    AoE는 대개 마감 목록 맨 위에 한 번만 선언되므로 raw_text에는 안 들어온다.
    그래서 페이지 전체를 근거로 본다.
    """
    page = ("Important Dates All times are in Anywhere on Earth (AoE) time zone "
            "Thursday, January 21, 2027 : Submission deadline")
    accepted, rejected = validate_extraction(
        [{"type": "poster", "label": "Posters", "date": "2027-01-21 23:59:59",
          "timezone": "AoE", "confidence": "high",
          "raw_text": "Thursday, January 21, 2027 : Submission deadline",
          "url": "https://chi2027.acm.org/authors/posters/"}],
        page, date(2027, 5, 10), date(2026, 9, 14),
    )
    assert rejected == []
    assert accepted[0]["timezone"] == "AoE"


def test_aoe_claim_is_rejected_when_the_page_never_says_it():
    """시간대도 근거가 있어야 한다. ACM MM 페이지에는 AoE 표기가 없다."""
    page = "Workshop proposals due February 12, 2026"
    accepted, rejected = validate_extraction(
        [{"type": "workshop", "label": "Workshops", "date": "2026-02-12 23:59:59",
          "timezone": "AoE", "confidence": "high", "raw_text": page,
          "url": "https://example.com"}],
        page, date(2026, 10, 1), date(2025, 9, 14),
    )
    assert accepted == []
    assert rejected[0]["reject_reason"] == "timezone_not_in_page"


def test_deadline_without_a_timezone_stays_without_one():
    """페이지가 안 밝힌 시간대를 지어내지 않는다."""
    page = "Author notification deadline (for archival papers): October 30, 2026"
    accepted, _ = validate_extraction(
        [{"type": "notification", "label": "Workshop author notification",
          "date": "2026-10-30 23:59:59", "confidence": "high", "raw_text": page,
          "url": "https://example.com"}],
        page, date(2027, 1, 4), date(2026, 9, 14),
    )
    assert "timezone" not in accepted[0]
