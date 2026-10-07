"""공식 사이트 추출값 검증 게이트 (설계 §7).

Hermes가 쓴 추출 JSON을 스크립트(fetch_pages.py)가 직접 받은 페이지 본문과
대조한다. 근거 페이지는 반드시 스크립트가 받은 것이어야 한다 - 추출자가
인용문과 그 근거를 둘 다 만들면 대조가 무의미해진다.
"""

from __future__ import annotations

import re
from datetime import date

from scripts.validate_scraped import (
    MAX_LEAD,
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
    accepted: dict = {"edition": None, "deadlines": []}
    rejected: list[dict] = []
    for item in extraction.get("items") or []:
        reason = check_common(item, pages, conference_start)
        if reason:
            rejected.append({**item, "reject_reason": reason})
        else:
            accepted["deadlines"].append(_accepted_deadline(item))
    return accepted, rejected
