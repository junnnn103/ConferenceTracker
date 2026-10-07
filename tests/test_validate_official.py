from datetime import date

from scripts.validate_official import (
    contains_ignoring_space,
    load_pages,
    validate_official,
)

URL = "https://chi2027.acm.org/authors/papers/"
PAGE = (
    "Important Dates All times are in Anywhere on Earth (AoE) time zone.\n"
    "Thursday, September 10, 2026 : Paper submission deadline, including videos\n"
)
START = date(2027, 5, 10)


def item(**over):
    base = {
        "type": "paper", "label": "Paper submission deadline",
        "date": "2026-09-10 23:59:59", "timezone": "AoE", "confidence": "high",
        "raw_text": "Thursday, September 10, 2026: Paper submission deadline, including videos",
        "url": URL,
    }
    base.update(over)
    return base


def run(*items, pages=None, start=START):
    extraction = {"abbr": "chi", "year": 2027, "items": list(items)}
    return validate_official(extraction, pages or {URL: PAGE}, start)


def test_whitespace_difference_is_not_a_mismatch():
    """2026-10-07 시험에서 '2026: Paper'와 '2026 : Paper' 차이로 실재 문장이 떨어졌다."""
    accepted, rejected = run(item())
    assert rejected == []
    assert accepted["deadlines"][0]["evidence"]["url"] == URL
    assert accepted["deadlines"][0]["timezone"] == "AoE"


def test_sentence_not_on_page_is_rejected():
    _, rejected = run(item(raw_text="Thursday, September 10, 2026: Abstract deadline"))
    assert rejected[0]["reject_reason"] == "raw_text_not_in_page"


def test_url_not_fetched_by_script_is_rejected():
    """추출자가 스스로 근거 페이지를 만들면 대조가 무의미하다 (Review Focus 3)."""
    _, rejected = run(item(url="https://example.com/made-up"))
    assert rejected[0]["reject_reason"] == "url_not_fetched"


def test_date_must_be_in_the_quoted_sentence():
    _, rejected = run(item(date="2026-09-11 23:59:59"))
    assert rejected[0]["reject_reason"] == "date_not_in_raw_text"


def test_aoe_needs_evidence_on_the_page():
    page = "Thursday, September 10, 2026 : Paper submission deadline, including videos"
    _, rejected = run(item(), pages={URL: page})
    assert rejected[0]["reject_reason"] == "timezone_not_in_page"


def test_utc_minus_12_counts_as_aoe_evidence():
    page = ("All deadlines are 11.59 pm UTC -12h. "
            "Thursday, September 10, 2026 : Paper submission deadline, including videos")
    _, rejected = run(item(), pages={URL: page})
    assert rejected == []


def test_deadline_after_conference_is_rejected():
    _, rejected = run(item(), start=date(2026, 9, 1))
    assert rejected[0]["reject_reason"] == "deadline_after_conference"


def test_low_confidence_and_unknown_type_are_rejected():
    _, rejected = run(item(confidence="low"), item(type="tutorial"))
    assert [r["reject_reason"] for r in rejected] == ["low_confidence", "unknown_type"]


def test_load_pages_splits_sections():
    text = "===== https://a/ =====\nalpha\n\n===== https://b/x =====\nbeta\n"
    pages = load_pages(text)
    assert set(pages) == {"https://a/", "https://b/x"}
    assert "alpha" in pages["https://a/"] and "beta" in pages["https://b/x"]


def test_contains_ignoring_space():
    assert contains_ignoring_space("a  b\nc", "abc")
    assert not contains_ignoring_space("abc", "")


ACL_URL = "https://2027.aclweb.org/"
ACL_PAGE = (
    "The 65th Annual Meeting of the Association for Computational Linguistics\n"
    "Kyoto, Japan\nAugust 17–22, 2027\n"
    "ARR submission deadline January 4, 2027\n"
    "All deadlines are 11.59 pm UTC -12h (anywhere on earth).\n"
)


def acl_edition(**over):
    base = {
        "date_text": "August 17-22, 2027", "start": "2027-08-17", "end": "2027-08-22",
        "place": "Kyoto, Japan", "raw_text": "Kyoto, Japan August 17–22, 2027",
        "url": ACL_URL, "confidence": "high",
    }
    base.update(over)
    return base


def run_acl(edition=None, *items):
    extraction = {"abbr": "acl", "year": 2027, "edition": edition, "items": list(items)}
    return validate_official(extraction, {ACL_URL: ACL_PAGE}, None)


def test_edition_with_range_and_place_is_accepted():
    accepted, rejected = run_acl(acl_edition())
    assert rejected == []
    assert accepted["edition"]["start"] == "2027-08-17"
    assert accepted["edition"]["place"] == "Kyoto, Japan"


def test_edition_accepts_ranges_in_both_orders():
    """Review Focus 1: DIS는 '28 June – 2 July 2027'처럼 일-월 순서로 쓴다."""
    url = "https://dis.acm.org/2027/"
    page = "Stockholm, Sweden 28 June – 2 July 2027"
    extraction = {"abbr": "dis", "year": 2027, "items": [], "edition": {
        "date_text": "June 28 - July 2, 2027", "start": "2027-06-28", "end": "2027-07-02",
        "place": "Stockholm, Sweden", "raw_text": page, "url": url, "confidence": "high"}}
    accepted, rejected = validate_official(extraction, {url: page}, None)
    assert rejected == [] and accepted["edition"]["end"] == "2027-07-02"
    page2 = "Stockholm, Sweden, June 28th – July 2nd 2027"
    extraction["edition"]["raw_text"] = page2
    accepted, rejected = validate_official(extraction, {url: page2}, None)
    assert rejected == []


def test_edition_end_must_be_in_the_sentence():
    _, rejected = run_acl(acl_edition(end="2027-08-23"))
    assert rejected[0]["reject_reason"] == "end_not_in_raw_text"


def test_edition_place_must_be_in_the_sentence():
    _, rejected = run_acl(acl_edition(place="Tokyo, Japan"))
    assert rejected[0]["reject_reason"] == "place_not_in_raw_text"


def test_edition_needs_high_confidence():
    _, rejected = run_acl(acl_edition(confidence="medium"))
    assert rejected[0]["reject_reason"] == "core_needs_high_confidence"


def test_edition_year_must_match_target():
    _, rejected = run_acl(acl_edition(start="2026-08-17", end="2026-08-22"))
    assert rejected[0]["reject_reason"] == "wrong_year"


def test_core_deadline_needs_high_confidence_but_poster_does_not():
    paper = {"type": "paper", "label": "ARR", "date": "2027-01-04 23:59:59", "timezone": "AoE",
             "confidence": "medium", "raw_text": "ARR submission deadline January 4, 2027", "url": ACL_URL}
    poster = {**paper, "type": "poster", "label": "Posters"}
    accepted, rejected = run_acl(None, paper, poster)
    assert [r["reject_reason"] for r in rejected] == ["core_needs_high_confidence"]
    assert [d["type"] for d in accepted["deadlines"]] == ["poster"]


def test_accepted_edition_start_bounds_the_deadlines():
    """회차가 통과하면 그 개최일로 게이트 4를 건다."""
    late = {"type": "paper", "label": "ARR", "date": "2027-01-04 23:59:59", "timezone": "AoE",
            "confidence": "high", "raw_text": "ARR submission deadline January 4, 2027", "url": ACL_URL}
    accepted, rejected = run_acl(acl_edition(), late)
    assert rejected == [] and len(accepted["deadlines"]) == 1
