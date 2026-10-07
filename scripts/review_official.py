"""반영 전 독립 검토 (설계 §7a).

게이트는 지어낸 값은 막지만 실재 문장을 잘못 해석한 것은 못 본다. 사이트를
바꿀 항목마다 Claude가 추출자의 답을 모른 채 원문만 보고 다시 해석한다.
두 해석이 같으면 반영, 다르거나 검토가 실패하면 반영하지 않는다.
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from scripts.models import normalize_place
from scripts.validate_official import squash

EXCERPT_WIDTH = 1500

# 검토 모델은 세션 기본값을 따르지 않고 고정한다. Task 12 역검증을 가벼운 모델부터
# 돌려 14/14를 맞힌 가장 가벼운 모델로 정한다. 2026-10-07 실측: 검토 한 건에 입력
# 4-7천 토큰. 같은 사례에서 Sonnet 5는 who_submits를 틀렸고 Haiku 4.5와 Opus는 맞혔다.
REVIEW_MODEL = "claude-haiku-4-5-20251001"

# 추출자의 type -> 검토자의 what으로 인정하는 값.
# poster와 lbw는 같은 층이다. 워크숍 논문 저자 통보는 소유자가 2026-09-14에
# 워크숍 일정의 기준으로 삼자고 정했다(WACV 2027 Author notification deadline).
# workshop은 기존 scraped 데이터의 타입으로, 역검증(Task 12)에서만 쓴다.
WHAT_FOR_TYPE = {
    "paper": {"paper"},
    "short_paper": {"short_paper"},
    "abstract": {"abstract"},
    "commitment": {"commitment"},
    "poster": {"poster", "lbw"},
    "lbw": {"poster", "lbw"},
    "notification": {"workshop_acceptance", "workshop_paper_notification"},
    "workshop": {"workshop_paper"},
}
SUBMITTED_BY_AUTHORS = {"paper", "short_paper", "abstract", "commitment", "poster", "lbw", "workshop"}

DEADLINE_PROMPT = """You are checking one date on an official conference website.
Read the excerpt and answer with JSON only, no other text.

Conference: <<CONFERENCE>> <<YEAR>>
Date to explain: <<DATE>>
Excerpt from <<URL>>:
<<<
<<EXCERPT>>
>>>

Answer exactly this JSON shape:
{"who_submits": "author|organizer|reviewer|none", "what": "paper|short_paper|abstract|commitment|poster|lbw|workshop_acceptance|workshop_paper_notification|workshop_paper|other", "event_year": 2027, "exact": true, "date": "YYYY-MM-DD"}

- who_submits: who must submit something by this date. "none" if it is an announcement.
- what: what the date is for.
  workshop_acceptance = the date the list of accepted workshops is announced or published.
  workshop_paper_notification = the date authors of workshop papers are notified.
  workshop_paper = the deadline for submitting papers to workshops.
  Workshop PROPOSALS submitted by organizers are "other" with who_submits "organizer".
- event_year: the year in which the conference itself takes place.
- exact: false if the page says approximately, tentative, TBA, or gives no exact day.
- date: the date you read in the excerpt for this item.
"""

EDITION_PROMPT = """You are checking an official conference website.
Read the excerpt and answer with JSON only, no other text.

Conference: <<CONFERENCE>> <<YEAR>>
Excerpt from <<URL>>:
<<<
<<EXCERPT>>
>>>

When and where is the main conference held? Answer exactly this JSON shape:
{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "place": "City, Country", "event_year": 2027}
"""


def excerpt(page: str, raw: str, width: int = EXCERPT_WIDTH) -> str:
    """원문에서 인용문 앞뒤 width자. 공백 차이를 무시하고 찾는다."""
    flat = " ".join((page or "").split())
    chars = squash(raw)
    if not chars:
        return ""
    m = re.search(r"\s*".join(re.escape(c) for c in chars), flat)
    if not m:
        return ""
    return flat[max(0, m.start() - width): m.end() + width]


def _fill(template: str, **values) -> str:
    for key, value in values.items():
        template = template.replace(f"<<{key}>>", str(value))
    return template


def build_deadline_prompt(conference, year, url, page, raw, date_str) -> str:
    return _fill(DEADLINE_PROMPT, CONFERENCE=conference, YEAR=year, DATE=date_str, URL=url,
                 EXCERPT=excerpt(page, raw))


def build_edition_prompt(conference, year, url, page, raw) -> str:
    return _fill(EDITION_PROMPT, CONFERENCE=conference, YEAR=year, URL=url, EXCERPT=excerpt(page, raw))


def parse_review(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        value = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def deadline_mismatches(item: dict, review: dict, year: int) -> list[str]:
    reasons = []
    if review.get("what") not in WHAT_FOR_TYPE.get(item["type"], set()):
        reasons.append(f"what:{review.get('what')}")
    expected_who = "author" if item["type"] in SUBMITTED_BY_AUTHORS else "none"
    if review.get("who_submits") != expected_who:
        reasons.append(f"who_submits:{review.get('who_submits')}")
    if str(review.get("date", ""))[:10] != str(item["date"])[:10]:
        reasons.append(f"date:{review.get('date')}")
    if review.get("event_year") != year:
        reasons.append(f"event_year:{review.get('event_year')}")
    if review.get("exact") is not True:
        reasons.append("not_exact")
    return reasons


def edition_mismatches(edition: dict, review: dict, year: int) -> list[str]:
    reasons = []
    if str(review.get("start", ""))[:10] != edition["start"]:
        reasons.append(f"start:{review.get('start')}")
    if str(review.get("end", ""))[:10] != edition["end"]:
        reasons.append(f"end:{review.get('end')}")
    if review.get("event_year") != year:
        reasons.append(f"event_year:{review.get('event_year')}")
    a = normalize_place(review.get("place")).lower().replace(" ", "")
    b = normalize_place(edition.get("place")).lower().replace(" ", "")
    if edition.get("place") and not (a and (a in b or b in a)):
        reasons.append(f"place:{review.get('place')}")
    return reasons


def claude_bin() -> str:
    # cron 환경에는 ~/.local/bin이 PATH에 없을 수 있다.
    return shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")


def ask_claude(prompt: str, timeout: int = 180, model: str | None = None) -> str:
    """도구 없이, 저장소 밖에서 부른다 - 프로젝트 문맥이 판단에 끼지 않게."""
    proc = subprocess.run(
        [claude_bin(), "-p", "--model", model or REVIEW_MODEL, "--tools", "",
         "--output-format", "json", "--no-session-persistence"],
        input=prompt, capture_output=True, text=True, timeout=timeout, cwd=tempfile.gettempdir(),
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[:200] or f"exit {proc.returncode}")
    payload = json.loads(proc.stdout)
    if payload.get("is_error"):
        raise RuntimeError(str(payload.get("result"))[:200])
    return payload.get("result") or ""


def _deadline_unchanged(item: dict, current: dict | None) -> bool:
    if not current:
        return False
    return any(d["type"] == item["type"] and str(d["date"])[:10] == item["date"][:10]
               for d in current.get("deadlines") or [])


def _edition_unchanged(edition: dict, current: dict | None) -> bool:
    if not current:
        return False
    return (str(current.get("start") or "")[:10], str(current.get("end") or "")[:10],
            normalize_place(current.get("place"))) == (
        edition["start"], edition["end"], normalize_place(edition.get("place")))


def _ask(ask, prompt) -> tuple[dict | None, list[str]]:
    try:
        answer = ask(prompt)
    except Exception as exc:  # 검토 없이 반영하는 경로는 두지 않는다
        return None, [f"review_failed: {exc}"[:200]]
    review_value = parse_review(answer)
    if review_value is None:
        return None, ["unparseable_review"]
    return review_value, []


def review(accepted: dict, pages: dict[str, str], conference: str, year: int,
           current: dict | None, ask=ask_claude) -> tuple[dict, list[dict]]:
    approved: dict = {"edition": None, "deadlines": []}
    held: list[dict] = []

    edition = accepted.get("edition")
    if edition:
        if _edition_unchanged(edition, current):
            approved["edition"] = edition
        else:
            url, raw = edition["evidence"]["url"], edition["evidence"]["raw_text"]
            value, reasons = _ask(ask, build_edition_prompt(conference, year, url, pages.get(url, ""), raw))
            reasons = reasons or edition_mismatches(edition, value, year)
            if reasons:
                held.append({"item": {**edition, "type": "edition"}, "review": value, "reasons": reasons})
            else:
                approved["edition"] = edition

    for item in accepted.get("deadlines") or []:
        if _deadline_unchanged(item, current):
            approved["deadlines"].append(item)
            continue
        url, raw = item["evidence"]["url"], item["evidence"]["raw_text"]
        prompt = build_deadline_prompt(conference, year, url, pages.get(url, ""), raw, item["date"][:10])
        value, reasons = _ask(ask, prompt)
        reasons = reasons or deadline_mismatches(item, value, year)
        if reasons:
            held.append({"item": item, "review": value, "reasons": reasons})
        else:
            approved["deadlines"].append(item)
    return approved, held
