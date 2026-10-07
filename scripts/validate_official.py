"""공식 사이트 추출값 검증 게이트 (설계 §7).

Hermes가 쓴 추출 JSON을 스크립트(fetch_pages.py)가 직접 받은 페이지 본문과
대조한다. 근거 페이지는 반드시 스크립트가 받은 것이어야 한다 - 추출자가
인용문과 그 근거를 둘 다 만들면 대조가 무의미해진다.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from scripts.validate_scraped import (
    MAX_LEAD,
    _MONTH_NUMBERS,
    _parse_datetime,
    mentions_date,
    normalize_whitespace,
)

CORE_TYPES = frozenset({"paper", "short_paper", "abstract", "commitment"})
SUB_TYPES = frozenset({"poster", "lbw", "notification"})
ALLOWED_TYPES = CORE_TYPES | SUB_TYPES

# ACL은 "UTC -12h (anywhere on earth)"처럼 쓴다.
AOE_RE = re.compile(r"anywhere[\s-]+on[\s-]+earth|\bAoE\b|UTC\s*-\s*12", re.IGNORECASE)
_SECTION_RE = re.compile(r"^===== (\S+) =====$", re.MULTILINE)


def squash(text) -> str:
    """모든 공백을 지운다. 대조할 때만 쓴다."""
    return re.sub(r"\s+", "", str(text or ""))


def contains_ignoring_space(haystack: str, needle: str) -> bool:
    """공백을 무시하고 needle이 haystack에 있는가.

    HTML 태그를 벗기는 방식에 따라 "2026: Paper"와 "2026 : Paper"처럼
    공백만 달라진다. 2026-10-07 시험에서 이 차이로 실재 문장 셋이 떨어졌다.
    """
    n = squash(needle)
    return bool(n) and n in squash(haystack)


def load_pages(text: str) -> dict[str, str]:
    """fetch_pages.py가 쓴 .txt를 주소별 본문으로 나눈다."""
    parts = _SECTION_RE.split(text or "")
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def check_common(item: dict, pages: dict[str, str], conference_start: date | None) -> str | None:
    """게이트 1–5. 모든 항목에 적용한다."""
    if str(item.get("confidence", "")).lower() == "low":
        return "low_confidence"
    if item.get("type") not in ALLOWED_TYPES:
        return "unknown_type"
    page = pages.get(item.get("url") or "")
    if page is None:
        return "url_not_fetched"
    raw = normalize_whitespace(item.get("raw_text") or "")
    if not raw or not contains_ignoring_space(page, raw):
        return "raw_text_not_in_page"
    when = _parse_datetime(item.get("date"))
    if when is None:
        return "unparseable_date"
    if not mentions_date(raw, when):
        return "date_not_in_raw_text"
    tz = str(item.get("timezone") or "").strip()
    if tz and AOE_RE.search(tz) and not AOE_RE.search(page):
        return "timezone_not_in_page"
    if conference_start is not None:
        if when.date() > conference_start:
            return "deadline_after_conference"
        if conference_start - when.date() > MAX_LEAD:
            return "deadline_too_early"
    return None


_RANGE = re.compile(
    r"\b(?P<m1>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<d1>\d{1,2})(?:st|nd|rd|th)?"
    r"\s*[-–—~]\s*"
    r"(?:(?P<m2>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?(?P<d2>\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)

_RANGE_DAY_MONTH = re.compile(
    r"\b(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s*[-–—~]\s*(?P<d2>\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*",
    re.IGNORECASE,
)

_RANGE_WORD_SEP = re.compile(
    r"\b(?P<m>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(?:to|through|until)\s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


def _at_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day)


def mentions_range(raw: str, start: date, end: date) -> bool:
    """개최일 범위가 문장에 있는가.

    "August 17–22, 2027"에서 22는 앞에 월이 없어 mentions_date가 못 찾는다.
    "June 28 – July 2"와 일-월 순서("28 June – 2 July")도 받는다.
    "17–22 August 2027"(공유 월), "August 17 to 22, 2027"(단어 구분자)도 받는다.
    """
    if mentions_date(raw, _at_midnight(start)) and mentions_date(raw, _at_midnight(end)):
        return True
    # Month-Day format: "August 17–22" or "June 28 – July 2"
    for m in _RANGE.finditer(raw or ""):
        m1 = _MONTH_NUMBERS[m["m1"].lower()[:3]]
        m2 = _MONTH_NUMBERS[(m["m2"] or m["m1"]).lower()[:3]]
        if (m1, int(m["d1"])) == (start.month, start.day) and (m2, int(m["d2"])) == (end.month, end.day):
            return True
    # Day-Month format: "17–22 August 2027"
    for m in _RANGE_DAY_MONTH.finditer(raw or ""):
        month = _MONTH_NUMBERS[m["month"].lower()[:3]]
        if (month, int(m["d1"])) == (start.month, start.day) and (month, int(m["d2"])) == (end.month, end.day):
            return True
    # Word separator format: "August 17 to 22, 2027"
    for m in _RANGE_WORD_SEP.finditer(raw or ""):
        month = _MONTH_NUMBERS[m["m"].lower()[:3]]
        if (month, int(m["d1"])) == (start.month, start.day) and (month, int(m["d2"])) == (end.month, end.day):
            return True
    return False


def _place_in(raw: str, place: str) -> bool:
    norm = lambda s: re.sub(r"[\s,]+", "", str(s or "")).lower()
    return bool(norm(place)) and norm(place) in norm(raw)


def _start_in_range(raw: str, start: date, end: date) -> bool:
    """Start date is mentioned either standalone or as beginning of a range."""
    if mentions_date(raw, _at_midnight(start)):
        return True
    # Check if any range in the text starts at the start date
    for m in _RANGE.finditer(raw or ""):
        m1 = _MONTH_NUMBERS[m["m1"].lower()[:3]]
        if (m1, int(m["d1"])) == (start.month, start.day):
            return True
    for m in _RANGE_DAY_MONTH.finditer(raw or ""):
        month = _MONTH_NUMBERS[m["month"].lower()[:3]]
        if (month, int(m["d1"])) == (start.month, start.day):
            return True
    for m in _RANGE_WORD_SEP.finditer(raw or ""):
        month = _MONTH_NUMBERS[m["m"].lower()[:3]]
        if (month, int(m["d1"])) == (start.month, start.day):
            return True
    return False


def _end_in_range(raw: str, start: date, end: date) -> bool:
    """End date is mentioned either standalone or as ending of a range that starts at start date."""
    if mentions_date(raw, _at_midnight(end)):
        return True
    # Check if any range in the text starts at start and ends at end
    for m in _RANGE.finditer(raw or ""):
        m1 = _MONTH_NUMBERS[m["m1"].lower()[:3]]
        m2 = _MONTH_NUMBERS[(m["m2"] or m["m1"]).lower()[:3]]
        if (m1, int(m["d1"])) == (start.month, start.day) and (m2, int(m["d2"])) == (end.month, end.day):
            return True
    for m in _RANGE_DAY_MONTH.finditer(raw or ""):
        month = _MONTH_NUMBERS[m["month"].lower()[:3]]
        if (month, int(m["d1"])) == (start.month, start.day) and (month, int(m["d2"])) == (end.month, end.day):
            return True
    for m in _RANGE_WORD_SEP.finditer(raw or ""):
        month = _MONTH_NUMBERS[m["m"].lower()[:3]]
        if (month, int(m["d1"])) == (start.month, start.day) and (month, int(m["d2"])) == (end.month, end.day):
            return True
    return False


def check_strict(item: dict, year: int) -> str | None:
    """게이트 6, 9 - 본 논문 마감에만. 바로 반영되고 업스트림 값을 덮으므로 더 엄격하게."""
    if item["type"] not in CORE_TYPES:
        return None
    if str(item.get("confidence", "")).lower() != "high":
        return "core_needs_high_confidence"
    if _parse_datetime(item["date"]).year not in (year - 1, year):
        return "wrong_year"
    return None


def check_edition(edition: dict, pages: dict[str, str], year: int) -> str | None:
    """게이트 1, 6–9 - 회차(개최일·장소)."""
    if str(edition.get("confidence", "")).lower() != "high":
        return "core_needs_high_confidence"
    page = pages.get(edition.get("url") or "")
    if page is None:
        return "url_not_fetched"
    raw = normalize_whitespace(edition.get("raw_text") or "")
    if not raw or not contains_ignoring_space(page, raw):
        return "raw_text_not_in_page"
    try:
        start = date.fromisoformat(str(edition.get("start")))
        end = date.fromisoformat(str(edition.get("end")))
    except ValueError:
        return "unparseable_date"
    if end < start:
        return "end_before_start"
    if start.year != year:
        return "wrong_year"
    if not _start_in_range(raw, start, end):
        return "start_not_in_raw_text"
    if not _end_in_range(raw, start, end):
        return "end_not_in_raw_text"
    if edition.get("place") and not _place_in(raw, edition["place"]):
        return "place_not_in_raw_text"
    return None


def _accepted_edition(edition: dict) -> dict:
    return {
        "date_text": normalize_whitespace(edition.get("date_text") or ""),
        "start": str(edition["start"]),
        "end": str(edition["end"]),
        "place": normalize_whitespace(edition.get("place") or ""),
        "evidence": {"raw_text": normalize_whitespace(edition["raw_text"]), "url": edition["url"]},
    }


def _accepted_deadline(item: dict) -> dict:
    when = _parse_datetime(item["date"])
    entry = {
        "type": item["type"],
        "label": str(item.get("label") or item["type"]),
        "date": when.strftime("%Y-%m-%d %H:%M:%S"),
    }
    tz = str(item.get("timezone") or "").strip()
    if tz:
        entry["timezone"] = tz
    entry["evidence"] = {
        "raw_text": normalize_whitespace(item["raw_text"]),
        "url": item["url"],
    }
    return entry


def validate_official(extraction: dict, pages: dict[str, str], conference_start: date | None):
    """통과 항목과 탈락 항목을 나눠 돌려준다. 한 항목이 떨어져도 나머지는 계속 본다."""
    year = int(extraction["year"])
    accepted: dict = {"edition": None, "deadlines": []}
    rejected: list[dict] = []

    edition = extraction.get("edition")
    if edition:
        reason = check_edition(edition, pages, year)
        if reason:
            rejected.append({**edition, "type": "edition", "reject_reason": reason})
        else:
            accepted["edition"] = _accepted_edition(edition)
            conference_start = date.fromisoformat(str(edition["start"]))

    for item in extraction.get("items") or []:
        reason = check_common(item, pages, conference_start) or check_strict(item, year)
        if reason:
            rejected.append({**item, "reject_reason": reason})
        else:
            accepted["deadlines"].append(_accepted_deadline(item))
    return accepted, rejected
