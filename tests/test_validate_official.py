from datetime import date

from scripts.validate_official import (
    contains_ignoring_space,
    load_pages,
    mentions_range,
    validate_official,
)

URL = "https://chi2027.acm.org/authors/papers/"
PAGE = (
    "CHI 2027 Important Dates All times are in Anywhere on Earth (AoE) time zone.\n"
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
    page = ("CHI 2027 All deadlines are 11.59 pm UTC -12h. "
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


def test_edition_accepts_day_month_order_range():
    """Fix round 1: '17–22 August 2027'(공유 월, 일-월 순서) 같은 범위를 받는다."""
    url = "https://dis.acm.org/2027/"
    page = "Stockholm, Sweden 17–22 August 2027"
    extraction = {"abbr": "dis", "year": 2027, "items": [], "edition": {
        "date_text": "August 17 - 22, 2027", "start": "2027-08-17", "end": "2027-08-22",
        "place": "Stockholm, Sweden", "raw_text": page, "url": url, "confidence": "high"}}
    accepted, rejected = validate_official(extraction, {url: page}, None)
    assert rejected == []
    assert accepted["edition"]["start"] == "2027-08-17"
    assert accepted["edition"]["place"] == "Stockholm, Sweden"


def test_edition_accepts_word_separator_range():
    """Fix round 1: 'August 17 to 22, 2027' 같은 단어 구분자 범위를 받는다."""
    url = "https://chi2027.acm.org/"
    page = "Kyoto, Japan August 17 to 22, 2027"
    extraction = {"abbr": "chi", "year": 2027, "items": [], "edition": {
        "date_text": "August 17 - 22, 2027", "start": "2027-08-17", "end": "2027-08-22",
        "place": "Kyoto, Japan", "raw_text": page, "url": url, "confidence": "high"}}
    accepted, rejected = validate_official(extraction, {url: page}, None)
    assert rejected == []
    assert accepted["edition"]["start"] == "2027-08-17"


def test_mentions_range_requires_word_boundary():
    """Fix round 1: word boundary 확인 - 'Summary 3-5'는 March 3-5로 매칭되지 않아야 한다."""
    from scripts.validate_official import mentions_range
    result = mentions_range("Summary 3-5", date(2027, 3, 3), date(2027, 3, 5))
    assert result is False


# Task 4: 해석 규칙 10-12
CHI_WS = "https://chi2027.acm.org/authors/workshops/"
CHI_WS_PAGE = (
    "Workshops - ACM CHI 2027\nImportant Dates All times are in Anywhere on Earth (AoE) time zone.\n"
    "Thursday, October 1, 2026 : Organizer submission deadline\n"
    "Thursday, December 17, 2026 : List of accepted workshops released by workshop chairs on the CHI website\n"
    "Participant submissions are due approximately Thursday, February 11, 2027 .\n"
)


def run_chi_ws(*items):
    extraction = {"abbr": "chi", "year": 2027, "items": list(items)}
    return validate_official(extraction, {CHI_WS: CHI_WS_PAGE}, date(2027, 5, 10))


def ws_item(type_, date_, raw, label="x"):
    return {"type": type_, "label": label, "date": date_, "timezone": "AoE",
            "confidence": "high", "raw_text": raw, "url": CHI_WS}


def test_organizer_deadline_cannot_be_a_submission():
    """2026-09부터 사이트에 실려 있던 CHI 오류. 문장도 날짜도 실재해서 게이트 1-5를 통과했다."""
    _, rejected = run_chi_ws(ws_item("poster", "2026-10-01 23:59:59",
                                     "Thursday, October 1, 2026 : Organizer submission deadline"))
    assert rejected[0]["reject_reason"] == "forbidden_word"


def test_approximate_date_is_never_applied():
    _, rejected = run_chi_ws(ws_item("notification", "2027-02-11 23:59:59",
                                     "Participant submissions are due approximately Thursday, February 11, 2027"))
    assert rejected[0]["reject_reason"] == "approximate"


def test_workshop_list_release_passes():
    accepted, rejected = run_chi_ws(ws_item("notification", "2026-12-17 23:59:59",
        "Thursday, December 17, 2026 : List of accepted workshops released by workshop chairs on the CHI website"))
    assert rejected == [] and accepted["deadlines"][0]["type"] == "notification"


def test_abstract_registration_is_not_forbidden():
    """Review Focus 2: 초록 마감은 흔히 'Abstract registration'이라고 부른다."""
    url = "https://example.org/2027/dates"
    page = "Example 2027 Important dates. Abstract registration deadline: March 1, 2027"
    extraction = {"abbr": "ex", "year": 2027, "items": [{
        "type": "abstract", "label": "Abstract registration", "date": "2027-03-01 23:59:59",
        "confidence": "high", "raw_text": "Abstract registration deadline: March 1, 2027", "url": url}]}
    accepted, rejected = validate_official(extraction, {url: page}, None)
    assert rejected == [] and accepted["deadlines"][0]["type"] == "abstract"


def test_registration_is_forbidden_for_paper():
    url = "https://example.org/2027/dates"
    page = "Example 2027. Paper registration deadline: March 1, 2027"
    extraction = {"abbr": "ex", "year": 2027, "items": [{
        "type": "paper", "label": "Paper", "date": "2027-03-01 23:59:59",
        "confidence": "high", "raw_text": "Paper registration deadline: March 1, 2027", "url": url}]}
    _, rejected = validate_official(extraction, {url: page}, None)
    assert rejected[0]["reject_reason"] == "forbidden_word"


def test_year_must_be_near_the_sentence():
    """작년 회차 페이지의 날짜를 올해 것으로 읽는 실수를 막는다."""
    url = "https://example.org/old"
    page = "Example 2026 Call for Papers. " + ("filler " * 600) + "Paper deadline: March 1, 2027"
    extraction = {"abbr": "ex", "year": 2028, "items": [{
        "type": "poster", "label": "Posters", "date": "2027-03-01 23:59:59",
        "confidence": "high", "raw_text": "Paper deadline: March 1, 2027", "url": url}]}
    _, rejected = validate_official(extraction, {url: page}, None)
    assert rejected[0]["reject_reason"] == "year_not_near"


def test_abstract_after_paper_is_out_of_order():
    url = "https://example.org/2027/dates"
    page = "Example 2027. Paper deadline: March 1, 2027. Abstract deadline: March 5, 2027"
    items = [
        {"type": "paper", "label": "Paper", "date": "2027-03-01 23:59:59", "confidence": "high",
         "raw_text": "Paper deadline: March 1, 2027", "url": url},
        {"type": "abstract", "label": "Abstract", "date": "2027-03-05 23:59:59", "confidence": "high",
         "raw_text": "Abstract deadline: March 5, 2027", "url": url},
    ]
    accepted, rejected = validate_official({"abbr": "ex", "year": 2027, "items": items}, {url: page}, None)
    assert [d["type"] for d in accepted["deadlines"]] == ["paper"]
    assert rejected[0]["reject_reason"] == "order"


def test_year_near_check_not_skipped_by_url_presence():
    """URL containing year doesn't skip year_near check. Year must appear in page near sentence or in page head."""
    url = "https://example.org/2028/old"  # URL contains 2028
    page = "Example 2026 Call for Papers. " + ("filler " * 600) + "Paper deadline: March 1, 2027"
    extraction = {"abbr": "ex", "year": 2028, "items": [{
        "type": "poster", "label": "Posters", "date": "2027-03-01 23:59:59",
        "confidence": "high", "raw_text": "Paper deadline: March 1, 2027", "url": url}]}
    _, rejected = validate_official(extraction, {url: page}, None)
    assert rejected[0]["reject_reason"] == "year_not_near"


def test_date_without_time_means_end_of_that_day():
    """원문이 날짜만 주면 그날이 끝날 때까지다.

    2026-10-08 시험 실행에서 CVPR "Submission Deadline Nov 16 '26 (Anywhere on
    Earth)"이 2026-11-16 00:00:00으로 추출됐다. 0시로 두면 AoE->KST 환산이 같은 날에
    머물러 사이트에 하루 이른 Nov 16으로 뜬다(실제로는 KST Nov 17 20:59까지).
    """
    url = "https://cvpr.thecvf.com/Conferences/2027/Dates"
    page = "CVPR 2027 Dates and Deadlines Submission Deadline Nov 16 '26 (Anywhere on Earth)"
    extraction = {"abbr": "cvpr", "year": 2027, "items": [{
        "type": "paper", "label": "Submission Deadline", "date": "2026-11-16 00:00:00",
        "timezone": "AoE", "confidence": "high",
        "raw_text": "Submission Deadline Nov 16 '26 (Anywhere on Earth)", "url": url}]}
    accepted, rejected = validate_official(extraction, {url: page}, None)
    assert rejected == []
    assert accepted["deadlines"][0]["date"] == "2026-11-16 23:59:59"


def test_explicit_time_is_kept():
    """원문이 시각을 밝혔으면 그대로 둔다 (CVPR 워크숍 결정 Dec 23 02:00 AM UTC)."""
    url = "https://cvpr.thecvf.com/Conferences/2027/Dates"
    page = "CVPR 2027 Workshop Proposal Decision Dec 23 '26 02:00 AM UTC"
    extraction = {"abbr": "cvpr", "year": 2027, "items": [{
        "type": "notification", "label": "Workshop Proposal Decision", "date": "2026-12-23 02:00:00",
        "confidence": "high", "raw_text": "Workshop Proposal Decision Dec 23 '26 02:00 AM UTC", "url": url}]}
    accepted, _ = validate_official(extraction, {url: page}, None)
    assert accepted["deadlines"][0]["date"] == "2026-12-23 02:00:00"


IUI_URL = "https://iui.acm.org/2027/call-for-posters-demos/"
IUI_PAGE = (
    "Call for Posters & Demos Skip to content Home Program "
    "Important Dates (AoE) All deadlines are 11:59 P.M. Anywhere on Earth (UTC -12:00). "
    "Submission Deadline: November 10th, 2026 Notification of acceptance : December 14th, 2026 "
    + ("Posters provide an opportunity for sharing ideas. " * 80)
    + "please select SIGCHI, IUI 2027, and IUI 2027 Posters"
)


def iui_poster(url=IUI_URL):
    return {"type": "poster", "label": "Submission Deadline", "date": "2026-11-10 23:59:59",
            "timezone": "AoE", "confidence": "high",
            "raw_text": "Submission Deadline: November 10th, 2026", "url": url}


def test_year_in_url_path_and_page_body_counts():
    """IUI 2027 포스터 페이지는 제목에 연도가 없고 "2027"이 인용문에서 2,700자 뒤에야 나온다.
    2026-10-12 자동 실행에서 year_not_near로 잘못 걸러졌다. 주소 경로가 /2027/이고 본문에도
    2027이 있으면 그 연도의 페이지로 본다."""
    accepted, rejected = validate_official(
        {"abbr": "iui", "year": 2027, "items": [iui_poster()]}, {IUI_URL: IUI_PAGE}, None)
    assert rejected == [] and accepted["deadlines"][0]["type"] == "poster"


def test_year_in_url_alone_is_not_enough():
    """주소에만 연도가 있고 본문 어디에도 없으면 여전히 탈락 (다른 연도 내용일 수 있다)."""
    page = IUI_PAGE.replace("IUI 2027", "IUI")
    _, rejected = validate_official(
        {"abbr": "iui", "year": 2027, "items": [iui_poster()]}, {IUI_URL: page}, None)
    assert rejected[0]["reject_reason"] == "year_not_near"


def test_year_in_page_body_alone_far_away_is_not_enough():
    """주소 경로에 연도가 없으면 기존 규칙(근처·머리)대로 본다."""
    url = "https://iui.acm.org/call-for-posters-demos/"
    _, rejected = validate_official(
        {"abbr": "iui", "year": 2027, "items": [iui_poster(url)]}, {url: IUI_PAGE}, None)
    assert rejected[0]["reject_reason"] == "year_not_near"


from scripts.validate_official import call_title


def test_call_title_strips_site_names_and_keeps_the_call():
    cases = {
        "Call for Posters & Demos": "Call for Posters & Demos",
        "Accepted Workshops - CIKM 2026": "Accepted Workshops",
        "CoRL 2026 - Call for Papers": "Call for Papers",
        "IEEE ICRA 2027 | Call for Technical Papers": "Call for Technical Papers",
        "Research Track: Call for Papers – KDD 2027": "Research Track: Call for Papers",
        "Call for Papers -": "Call for Papers",
        "ICLR 2027 Call for Papers": "Call for Papers",
        "﻿ IEEE BigData 2026": "",
        "KDD 2027 – KDD 2027 | San Jose": "",
    }
    keys = {"CoRL 2026 - Call for Papers": "corl", "IEEE ICRA 2027 | Call for Technical Papers": "icra",
            "Research Track: Call for Papers – KDD 2027": "kdd", "ICLR 2027 Call for Papers": "iclr",
            "﻿ IEEE BigData 2026": "bigdata", "KDD 2027 – KDD 2027 | San Jose": "kdd",
            "Accepted Workshops - CIKM 2026": "cikm"}
    for title, want in cases.items():
        assert call_title(title + "\nbody text", keys.get(title, "iui")) == want, title


def test_generic_label_gets_the_call_name():
    """IUI 2027 포스터 마감의 원문 라벨은 "Submission Deadline:"뿐이라 무슨 마감인지 안 보였다.
    그 페이지가 Call for Posters & Demos이니 그 이름을 붙인다."""
    page = "Call for Posters & Demos\n" + IUI_PAGE
    accepted, _ = validate_official({"abbr": "iui", "year": 2027, "items": [
        {**iui_poster(), "label": "Submission Deadline:"}]}, {IUI_URL: page}, None)
    assert accepted["deadlines"][0]["label"] == "Submission Deadline: Call for Posters & Demos"


def test_specific_label_is_left_alone():
    page = "Call for Posters & Demos\n" + IUI_PAGE
    accepted, _ = validate_official({"abbr": "iui", "year": 2027, "items": [
        {**iui_poster(), "label": "Poster submission deadline"}]}, {IUI_URL: page}, None)
    assert accepted["deadlines"][0]["label"] == "Poster submission deadline"
