# 공식 사이트 주간 확인 (Hermes) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 정보가 부족한 학회만 골라 매주 공식 사이트를 읽고, 검증 게이트와 Claude 독립 검토를 통과한 값을 사이트에 바로 반영한 뒤 디스코드로 알린다.

**Architecture:** 대상 선정·페이지 수집·검증·검토 호출·반영·보고는 저장소의 Python 스크립트가 하고, Hermes(gpt-6-luna)는 스크립트가 받아 둔 페이지 텍스트를 읽어 추출 JSON을 쓰는 일만 한다. 검증을 통과한 값은 새 출처 `official`(`data/official/<key>.yaml`)로 쌓이고, `build.py`가 업스트림 회차 위에 칸 단위로 덮는다. Hermes `research` 프로필의 cron이 매주 월 10:00 KST에 전체를 돈다.

**Tech Stack:** Python 3.11+(로컬 `.venv`는 3.14), PyYAML, requests, pytest, Node 20(`node --test`), Hermes Agent CLI(`research`), Claude Code CLI(`claude -p`).

**Spec:** `docs/superpowers/specs/2026-10-07-hermes-official-check-design.md` — 각 태스크는 이 문서의 절 번호(§)를 근거로 한다. 실행자는 둘 다 읽는다.

## Global Constraints

- Python 코드는 3.11에서도 돌아야 한다 (GitHub Actions가 3.11). 로컬 명령은 모두 `.venv/bin/python`으로 실행한다.
- 새 런타임 의존성 금지. 쓸 수 있는 것은 PyYAML, requests, 표준 라이브러리뿐.
- 추적 트랙: `paper`, `short_paper`, `abstract`, `commitment`(+ai-deadlines의 `commitment_deadline`), `poster`, `lbw`, `notification`(워크숍 채택 발표 또는 워크숍 논문 저자 통보). 튜토리얼·데모·박사과정 컨소시엄·워크숍 **제안** 마감은 절대 싣지 않는다.
- 한 번에 최대 12개 학회. 순서 A → B → D → E(마감 30일 이내) → E → C, 같은 기준 안에서는 가장 오래 확인하지 않은 학회부터 (§4).
- 학회당 최대 8페이지, 요청 사이 1초, 브라우저 User-Agent (§6).
- 검증 게이트 번호는 §7의 1–12를 그대로 쓴다.
- 독립 검토: 검토자에게 추출자의 `type`/`label`을 주지 않는다. 불일치 → 반영 안 함. 검토 호출 실패 → 반영 안 함. 사이트를 바꾸는 항목이 검토 없이 반영되는 경로는 없다 (§7a).
- 알림: `research send -t discord`, 메시지 2,000자 이하, 스크립트가 만든 보고서만 보낸다 (§10).
- `docs/data/conferences.json`은 파생 파일이다. 충돌 시 손으로 병합하지 않고 다시 빌드한다 (§11).
- 커밋 메시지는 한국어. 사람이 만드는 커밋은 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`과 `Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv`를 붙인다. Hermes cron이 만드는 자동 커밋에는 붙이지 않는다.
- 이 프로젝트의 관례: 새 테스트마다 해당 구현을 잠깐 되돌려 테스트가 실패하는지 확인한다(판별 확인). 각 태스크의 마지막 확인 단계에 포함돼 있다.

## Review Focus

명세가 직접 말하지 않지만 실제로 부딪힐 입력 다섯 가지. 각각 담당 태스크에 테스트가 들어 있다.

1. **일-월 순서나 범위 표기의 개최일** ("28 June – 2 July 2027", "August 17–22, 2027") — 개최일 게이트가 통과시켜야 한다. Task 3 `test_edition_accepts_ranges_in_both_orders`.
2. **"Abstract registration deadline"** — 금지어 `registration` 때문에 초록 마감이 떨어지면 안 된다. Task 4 `test_abstract_registration_is_not_forbidden`.
3. **추출자가 스크립트가 받지 않은 주소를 근거로 대는 경우** — 근거를 스스로 만든 것이므로 `url_not_fetched`로 떨어져야 한다. Task 2 `test_url_not_fetched_by_script_is_rejected`.
4. **Hermes push 직전에 GitHub Actions가 `conferences.json`을 바꾼 경우** — rebase 충돌을 손 병합 없이 다시 빌드로 풀어야 한다. Task 11 `test_push_conflict_rebuilds_instead_of_merging`.
5. **결합 행(ICCV/ECCV)** — 공식 값 파일은 구성원 이름(`iccv`)으로 쌓이고, 대상 선정과 빌드가 같은 키를 써야 한다. Task 6 `test_official_applies_to_combined_row_member`, Task 7 `test_combined_row_uses_member_key`.

추가로 cron 환경에서 `claude`와 `research`가 PATH에 없을 수 있다 — Task 9·10에서 절대 경로 폴백을 테스트한다.

## 파일 구조

| 파일 | 책임 | 태스크 |
|---|---|---|
| `scripts/models.py` | `PAPER_TYPES` 확장, `OfficialEdition` 추가 | 1, 5 |
| `docs/lib.js` | `PAPER_TYPES` 확장 | 1 |
| `scripts/validate_official.py` | 게이트 1–12 (순수 함수) | 2, 3, 4 |
| `scripts/merge.py` | `apply_official` | 5 |
| `scripts/sources/official.py` | `data/official/*.yaml` 읽기·병합·쓰기 | 6 |
| `scripts/build.py` | `official` 출처 적용 | 6 |
| `scripts/checklog.py` | 확인 기록과 재확인 주기 | 7 |
| `scripts/gaps.py` | 대상 선정 A–E | 7 |
| `scripts/fetch_pages.py` | 3단계 페이지 수집 | 8 |
| `scripts/review_official.py` | Claude 독립 검토 | 9 |
| `scripts/report.py` | 보고서·요약·디스코드 전송 | 10 |
| `scripts/official_run.py` | `prep`/`apply` 오케스트레이션 | 11 |
| `docs/hermes/official-check.md` | Hermes 지시문 | 11 |
| `scripts/hermes_prep.sh` | cron 사전 스크립트 | 11 |
| `scripts/backtest_review.py` | 검토자 역검증 (실제 Claude) | 12 |
| `tests/fixtures/official/` | ACL·CHI 페이지 고정 입력, 역검증 사례 | 8, 11, 12 |

---

### Task 1: 로컬 환경, 그리고 commitment·short_paper를 본 논문으로

설계 §8 "화면의 타입 처리", §12 준비 작업.

**Files:**
- Modify: `scripts/models.py:16` (`PAPER_TYPES`)
- Modify: `docs/lib.js:20` (`PAPER_TYPES`)
- Test: `tests/test_models.py`, `tests/js/lib.test.mjs`

**Interfaces:**
- Produces: Python `PAPER_TYPES = ("paper", "short_paper", "commitment", "commitment_deadline")`, JS 같은 목록. 이후 모든 태스크가 이 네 타입을 본 논문으로 본다.

- [ ] **Step 1: 로컬 가상환경을 만들고 기존 테스트가 도는지 확인**

OS 업그레이드로 시스템 Python의 패키지가 사라졌다. `.venv`는 이미 `.gitignore`에 있다.

```bash
cd /Users/jay/Agents/ConferenceManager
python3 -m venv .venv
.venv/bin/pip install -q -e ".[dev,bootstrap]"
.venv/bin/python -m pytest -q
node --test tests/js/
```
Expected: `168 passed`, `ℹ pass 78`, `ℹ fail 0`.

- [ ] **Step 2: Python 실패 테스트 작성**

`tests/test_models.py` 끝에 추가 (상단에 `from datetime import datetime`과 `from scripts.models import Deadline, Edition`이 없으면 추가):

```python
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
```

- [ ] **Step 3: JS 실패 테스트 작성**

`tests/js/lib.test.mjs` 끝에 추가 (`formatDeadline`은 이미 import돼 있다):

```javascript
test("ARR 마감이 지나면 commitment 마감이 대표가 된다", () => {
  const edition = {
    year: 2027, date_text: "", start: "2027-08-17", end: "2027-08-22",
    place: "Kyoto Japan", link: null, source: "ccfddl",
    primary_deadline: "2027-03-01T23:59:59",
    deadlines: [
      { type: "paper", label: "ARR Submission", date: "2027-01-04T23:59:59", timezone: "AoE", source: "ccfddl" },
      { type: "commitment", label: "Commitment deadline", date: "2027-03-01T23:59:59", timezone: "AoE", source: "official" },
    ],
  };
  assert.equal(formatDeadline(edition, new Date(2026, 9, 7)).label, "ARR Submission");
  assert.equal(formatDeadline(edition, new Date(2027, 0, 20)).label, "Commitment deadline");
});

test("commitment_deadline과 short_paper도 본 논문 후보다", () => {
  const edition = {
    year: 2026, date_text: "", start: "2026-07-02", end: "2026-07-07",
    place: "San Diego USA", link: null, source: "ai-deadlines",
    primary_deadline: "2026-03-14T23:59:59",
    deadlines: [
      { type: "paper", label: "Paper submission deadline", date: "2026-01-05T23:59:59", timezone: "AoE", source: "ai-deadlines" },
      { type: "commitment_deadline", label: "ARR commitment deadline", date: "2026-03-14T23:59:59", timezone: "AoE", source: "ai-deadlines" },
      { type: "short_paper", label: "Short papers", date: "2026-02-01T23:59:59", timezone: "AoE", source: "official" },
    ],
  };
  assert.equal(formatDeadline(edition, new Date(2026, 0, 20)).label, "Short papers");
  assert.equal(formatDeadline(edition, new Date(2026, 1, 10)).label, "ARR commitment deadline");
});
```

- [ ] **Step 4: 실패 확인**

```bash
.venv/bin/python -m pytest -q tests/test_models.py
node --test tests/js/
```
Expected: Python 2 failed (primary_deadline이 각각 2027-01-04, 2026-05-01), JS 2 failed.

- [ ] **Step 5: 구현**

`scripts/models.py`의 `PAPER_TYPES` 줄을 바꾼다:

```python
# commitment(ACL/EACL 등 ARR 학회가 쓰는 "이 학회로 제출 확정" 마감)과
# short_paper도 본 논문 마감이다. ai-deadlines는 commitment를
# commitment_deadline이라는 이름으로 준다.
PAPER_TYPES = ("paper", "short_paper", "commitment", "commitment_deadline")
```

`docs/lib.js`의 `PAPER_TYPES` 줄을 바꾼다:

```javascript
// scripts/models.py의 PAPER_TYPES와 같아야 한다.
const PAPER_TYPES = ["paper", "short_paper", "commitment", "commitment_deadline"];
```

- [ ] **Step 6: 통과와 판별 확인**

```bash
.venv/bin/python -m pytest -q && node --test tests/js/
```
Expected: `172 passed`, JS `ℹ fail 0`. 그다음 `scripts/models.py`의 `PAPER_TYPES`를 잠깐 `("paper",)`로 되돌려 새 Python 테스트 2개가 실패하는지, `docs/lib.js`를 `["paper"]`로 되돌려 새 JS 테스트 2개가 실패하는지 확인하고 원복한다.

- [ ] **Step 7: 빌드 결과 확인 후 커밋**

```bash
.venv/bin/python -m scripts.build
.venv/bin/python scripts/stamp_assets.py
git diff --stat
```
`conferences.json`에서 `primary_deadline`이 바뀌는 학회(ACL 2026 등)가 있을 수 있다. 그 외 변경이 없는지 확인한다.

```bash
git add scripts/models.py docs/lib.js tests/test_models.py tests/js/lib.test.mjs docs/data/conferences.json docs/index.html docs/app.js
git commit -m "commitment·short_paper를 본 논문 마감으로 취급

ARR 학회(ACL, EACL 등)는 ARR 마감이 지나면 commitment가 그 학회의 실제
마감이다. paper만 본 논문으로 치면 commitment가 올라와도 대표 마감이
되지 못한다. ai-deadlines가 쓰는 commitment_deadline도 같은 것으로 본다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
```

---

### Task 2: 공통 게이트 1–5 (`validate_official.py`)

설계 §7 "검증 게이트" 1–5. 근거 페이지는 반드시 스크립트가 받은 것이어야 하고, 비교할 때만 공백을 무시한다.

**Files:**
- Create: `scripts/validate_official.py`
- Test: `tests/test_validate_official.py`

**Interfaces:**
- Consumes: `scripts.validate_scraped`의 `MAX_LEAD`, `_parse_datetime`, `mentions_date`, `normalize_whitespace` (기존)
- Produces:
  - `CORE_TYPES`, `SUB_TYPES`, `ALLOWED_TYPES: frozenset[str]`
  - `squash(text) -> str`, `contains_ignoring_space(haystack: str, needle: str) -> bool`
  - `load_pages(text: str) -> dict[str, str]` — `===== <url> =====` 머리줄로 나눈 주소별 본문
  - `check_common(item: dict, pages: dict[str, str], conference_start: date | None) -> str | None` — 탈락 사유 또는 None
  - `validate_official(extraction: dict, pages: dict[str, str], conference_start: date | None) -> tuple[dict, list[dict]]` — `({"edition": dict | None, "deadlines": [dict]}, rejected)`. 통과 항목 형식: `{"type", "label", "date": "YYYY-MM-DD HH:MM:SS", "timezone"?, "evidence": {"raw_text", "url"}}`. 탈락 항목: 원래 항목 + `"reject_reason"`.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_validate_official.py`:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_validate_official.py`
Expected: `ModuleNotFoundError: No module named 'scripts.validate_official'`

- [ ] **Step 3: 구현**

`scripts/validate_official.py`:

```python
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
```

- [ ] **Step 4: 통과와 판별 확인**

Run: `.venv/bin/python -m pytest -q tests/test_validate_official.py`
Expected: `10 passed`.

판별 확인: `contains_ignoring_space`를 `return normalize_whitespace(needle) in normalize_whitespace(haystack)`로 잠깐 바꾸면 `test_whitespace_difference_is_not_a_mismatch`가 실패해야 한다. `page = pages.get(...)`가 None일 때 바로 반환하는 줄을 지우고 `page = pages.get(url) or "".join(pages.values())`로 바꾸면 `test_url_not_fetched_by_script_is_rejected`가 실패해야 한다. 원복.

- [ ] **Step 5: 커밋**

```bash
git add scripts/validate_official.py tests/test_validate_official.py
git commit -m "공식 사이트 추출값 공통 게이트(1-5)

근거 페이지는 스크립트가 받은 것만 인정하고(url_not_fetched), 대조할 때만
공백을 무시한다. 2026-10-07 시험에서 '2026: Paper'와 '2026 : Paper'
차이로 실재 문장 셋이 떨어졌다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
```

---

### Task 3: 회차·본 논문용 엄격 게이트 6–9

설계 §7 "회차와 본 논문 마감에는 추가로" 6–9.

**Files:**
- Modify: `scripts/validate_official.py`
- Test: `tests/test_validate_official.py`

**Interfaces:**
- Consumes: Task 2의 `check_common`, `contains_ignoring_space`, `_accepted_deadline`
- Produces:
  - `check_strict(item: dict, year: int) -> str | None`
  - `check_edition(edition: dict, pages: dict[str, str], year: int) -> str | None`
  - `mentions_range(raw: str, start: date, end: date) -> bool`
  - `validate_official`가 `extraction["edition"]`도 처리. 통과한 회차 형식: `{"date_text", "start": "YYYY-MM-DD", "end", "place", "evidence": {"raw_text", "url"}}`. 탈락한 회차는 `{**edition, "type": "edition", "reject_reason": ...}`.

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_validate_official.py` 끝에 추가:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_validate_official.py`
Expected: 새 테스트 8개 실패 (edition을 아직 처리하지 않음, `core_needs_high_confidence` 없음).

- [ ] **Step 3: 구현**

`scripts/validate_official.py` 상단 import를 바꾼다:

```python
from datetime import date, datetime

from scripts.validate_scraped import (
    MAX_LEAD,
    _MONTH_NUMBERS,
    _parse_datetime,
    mentions_date,
    normalize_whitespace,
)
```

`_accepted_deadline` 위에 추가:

```python
_RANGE = re.compile(
    r"(?P<m1>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<d1>\d{1,2})(?:st|nd|rd|th)?"
    r"\s*[-–—~]\s*"
    r"(?:(?P<m2>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?(?P<d2>\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


def _at_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day)


def mentions_range(raw: str, start: date, end: date) -> bool:
    """개최일 범위가 문장에 있는가.

    "August 17–22, 2027"에서 22는 앞에 월이 없어 mentions_date가 못 찾는다.
    "June 28 – July 2"와 일-월 순서("28 June – 2 July")도 받는다.
    """
    if mentions_date(raw, _at_midnight(start)) and mentions_date(raw, _at_midnight(end)):
        return True
    for m in _RANGE.finditer(raw or ""):
        m1 = _MONTH_NUMBERS[m["m1"].lower()[:3]]
        m2 = _MONTH_NUMBERS[(m["m2"] or m["m1"]).lower()[:3]]
        if (m1, int(m["d1"])) == (start.month, start.day) and (m2, int(m["d2"])) == (end.month, end.day):
            return True
    return False


def _place_in(raw: str, place: str) -> bool:
    norm = lambda s: re.sub(r"[\s,]+", "", str(s or "")).lower()
    return bool(norm(place)) and norm(place) in norm(raw)


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
    if not mentions_date(raw, _at_midnight(start)):
        return "start_not_in_raw_text"
    if not mentions_range(raw, start, end):
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
```

`validate_official`을 통째로 바꾼다:

```python
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
```

- [ ] **Step 4: 통과와 판별 확인**

Run: `.venv/bin/python -m pytest -q tests/test_validate_official.py`
Expected: `18 passed`.

판별 확인: `mentions_range`의 `for m in _RANGE...` 블록을 지우면 `test_edition_with_range_and_place_is_accepted`와 `test_edition_accepts_ranges_in_both_orders`가 실패해야 한다. `check_strict`의 confidence 검사를 지우면 `test_core_deadline_needs_high_confidence_but_poster_does_not`가 실패해야 한다. 원복.

- [ ] **Step 5: 커밋**

```bash
git add scripts/validate_official.py tests/test_validate_official.py
git commit -m "회차·본 논문 마감용 엄격 게이트(6-9)

바로 반영되고 업스트림 값을 덮는 항목이라 신뢰도 high만 받고, 개최일
범위와 장소가 인용문에 그대로 있어야 한다. 'August 17–22'와
'28 June – 2 July' 같은 범위 표기를 모두 받는다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
```

---

### Task 4: 해석 규칙 10–12

설계 §7 해석 규칙. 2026-09의 CHI 오류(워크숍 제안 마감을 제출 마감으로 해석)는 금지어 규칙만으로도 걸린다.

**Files:**
- Modify: `scripts/validate_official.py`
- Test: `tests/test_validate_official.py`

**Interfaces:**
- Consumes: Task 3의 `validate_official`, `check_common`, `check_strict`
- Produces:
  - `check_interpretation(item: dict, pages: dict[str, str], year: int) -> str | None` — 사유 `"approximate"`, `"forbidden_word"`, `"year_not_near"`
  - `year_near(page: str, raw: str, year: int, width: int = 1500) -> bool`
  - `check_order(deadlines: list[dict]) -> tuple[list[dict], list[dict]]` — 사유 `"order"`

- [ ] **Step 1: 실패 테스트 추가**

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_validate_official.py`
Expected: 새 테스트 중 6개 실패 (`test_workshop_list_release_passes`와 `test_abstract_registration_is_not_forbidden`는 이미 통과).

- [ ] **Step 3: 구현**

`check_edition` 아래에 추가:

```python
SUBMISSION_TYPES = CORE_TYPES | {"poster", "lbw"}

# 제출 마감이 아니라는 신호. 2026-09의 CHI 오류("Organizer submission
# deadline"을 워크숍 제출 마감으로 해석)는 이 규칙만으로도 걸린다.
_FORBIDDEN_WORDS = re.compile(
    r"\b(proposals?|organi[sz]ers?|jurors?|reviewers?|camera[\s-]*ready|registration|e-rights)\b",
    re.IGNORECASE,
)
_APPROXIMATE = re.compile(r"\bapproximately\b", re.IGNORECASE)


def year_near(page: str, raw: str, year: int, width: int = 1500) -> bool:
    """인용문 앞뒤 width자 안이나 페이지 머리(제목 등)에 대상 연도가 있는가."""
    flat, needle, y = squash(page), squash(raw), str(year)
    i = flat.find(needle)
    if i < 0:
        return False
    return y in flat[max(0, i - width): i + len(needle) + width] or y in flat[:2000]


def check_interpretation(item: dict, pages: dict[str, str], year: int) -> str | None:
    """게이트 10, 12. 실재하는 문장을 잘못 해석한 것을 잡는다."""
    raw = item.get("raw_text") or ""
    if _APPROXIMATE.search(raw):
        return "approximate"
    if item["type"] in SUBMISSION_TYPES:
        words = {w.lower() for w in _FORBIDDEN_WORDS.findall(raw)}
        if item["type"] == "abstract":
            # 초록 마감은 흔히 "Abstract registration"이라고 부른다.
            words.discard("registration")
        if words:
            return "forbidden_word"
    if not year_near(pages[item["url"]], raw, year):
        return "year_not_near"
    return None


def check_order(deadlines: list[dict]) -> tuple[list[dict], list[dict]]:
    """게이트 11. 초록은 본 논문보다 늦을 수 없고 commitment는 본 논문보다 이를 수 없다.

    워크숍 채택 발표는 본 논문과 순서가 정해져 있지 않아 보지 않는다.
    """
    papers = [_parse_datetime(d["date"]) for d in deadlines if d["type"] == "paper"]
    if not papers:
        return deadlines, []
    first = min(papers)
    kept, bad = [], []
    for d in deadlines:
        when = _parse_datetime(d["date"])
        if (d["type"] == "abstract" and when > first) or (d["type"] == "commitment" and when < first):
            bad.append({**d, "reject_reason": "order"})
        else:
            kept.append(d)
    return kept, bad
```

`validate_official`의 항목 루프와 반환부를 바꾼다:

```python
    for item in extraction.get("items") or []:
        reason = (
            check_common(item, pages, conference_start)
            or check_strict(item, year)
            or check_interpretation(item, pages, year)
        )
        if reason:
            rejected.append({**item, "reject_reason": reason})
        else:
            accepted["deadlines"].append(_accepted_deadline(item))

    kept, out_of_order = check_order(accepted["deadlines"])
    accepted["deadlines"] = kept
    rejected.extend(out_of_order)
    return accepted, rejected
```

- [ ] **Step 4: 통과와 판별 확인**

Run: `.venv/bin/python -m pytest -q tests/test_validate_official.py`
Expected: `25 passed`.

판별 확인: `words.discard("registration")`를 지우면 `test_abstract_registration_is_not_forbidden`이 실패해야 한다. `if words:` 블록을 지우면 `test_organizer_deadline_cannot_be_a_submission`이 실패해야 한다. `year_near`의 첫 return을 `return True`로 바꾸면 `test_year_must_be_near_the_sentence`가 실패해야 한다. 원복.

- [ ] **Step 5: 커밋**

```bash
git add scripts/validate_official.py tests/test_validate_official.py
git commit -m "해석 규칙(10-12): 금지어, 순서, 연도

게이트 1-5는 지어낸 값을 막지만 실재 문장을 잘못 해석한 것은 못 본다.
2026-09의 CHI 오류('Organizer submission deadline'을 워크숍 제출 마감으로
해석)는 금지어 규칙만으로도 걸린다. 초록의 'registration'은 예외.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
```

---

### Task 5: `OfficialEdition`과 `apply_official`

설계 §8. 회차를 통째로 바꾸지 않고 확인된 칸만 덮는다.

**Files:**
- Modify: `scripts/models.py` (클래스 추가)
- Modify: `scripts/merge.py`
- Test: `tests/test_merge.py`

**Interfaces:**
- Produces:
  - `scripts.models.OfficialEdition(year: int, date_text: str = "", start: date | None = None, end: date | None = None, place: str = "", deadlines: list[Deadline] = [])`
  - `scripts.merge.OFFICIAL_REPLACE_TYPES: frozenset[str]` = paper, short_paper, abstract, commitment, poster, lbw
  - `scripts.merge.apply_official(edition: Edition | None, off: OfficialEdition) -> Edition | None`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_merge.py`의 import에 `apply_official`을 더하고(`from scripts.merge import (... apply_official, ...)`), `from scripts.models import Deadline, Edition, OfficialEdition`으로 바꾼 뒤 끝에 추가:

```python
def _upstream_2027():
    return Edition(
        year=2027, date_text="TBD", start=None, end=None, place="Somewhere", link="https://x/2027",
        deadlines=[
            Deadline("paper", "Round 1", datetime(2026, 6, 26, 23, 59, 59), "AoE", "ai-deadlines"),
            Deadline("paper", "Round 2", datetime(2026, 8, 28, 23, 59, 59), "AoE", "ai-deadlines"),
            Deadline("review_release", "Reviews", datetime(2026, 10, 9), "AoE", "ai-deadlines"),
            Deadline("commitment_deadline", "Commitment", datetime(2026, 11, 1), "AoE", "ai-deadlines"),
            Deadline("notification", "Workshop acceptance", datetime(2026, 8, 15), None, "cfp-scrape"),
        ],
        source="ai-deadlines",
    )


def test_official_overwrites_dates_and_place_only():
    off = OfficialEdition(year=2027, date_text="January 4-8, 2027", start=date(2027, 1, 4),
                          end=date(2027, 1, 8), place="Orlando, FL, USA")
    out = apply_official(_upstream_2027(), off)
    assert (out.start, out.end, out.place, out.date_text) == (
        date(2027, 1, 4), date(2027, 1, 8), "Orlando FL USA", "January 4-8, 2027")
    assert out.link == "https://x/2027"
    assert [d.type for d in out.deadlines].count("review_release") == 1, "세부 일정은 보존"


def test_official_replaces_a_type_as_a_whole():
    """롤링 마감처럼 한 타입이 여러 번 나오므로 하나씩이 아니라 타입 단위로 바꾼다."""
    off = OfficialEdition(year=2027, deadlines=[
        Deadline("paper", "Paper submission", datetime(2026, 9, 1, 23, 59, 59), "AoE", "official")])
    out = apply_official(_upstream_2027(), off)
    papers = [d for d in out.deadlines if d.type == "paper"]
    assert [d.label for d in papers] == ["Paper submission"]


def test_official_commitment_replaces_ai_deadlines_commitment_deadline():
    off = OfficialEdition(year=2027, deadlines=[
        Deadline("commitment", "Commitment deadline", datetime(2026, 11, 3), "AoE", "official")])
    out = apply_official(_upstream_2027(), off)
    types = [d.type for d in out.deadlines]
    assert "commitment" in types and "commitment_deadline" not in types


def test_official_keeps_upstream_types_it_did_not_mention():
    off = OfficialEdition(year=2027, deadlines=[
        Deadline("poster", "Posters", datetime(2026, 11, 20), "AoE", "official")])
    out = apply_official(_upstream_2027(), off)
    assert [d.type for d in out.deadlines].count("paper") == 2


def test_official_notification_is_added_unless_identical():
    same = Deadline("notification", "workshop acceptance", datetime(2026, 8, 15), None, "official")
    other = Deadline("notification", "Workshop author notification", datetime(2026, 10, 30), None, "official")
    out = apply_official(_upstream_2027(), OfficialEdition(year=2027, deadlines=[same, other]))
    labels = [d.label for d in out.deadlines if d.type == "notification"]
    assert labels == ["Workshop acceptance", "Workshop author notification"]


def test_official_creates_missing_edition_only_with_dates():
    assert apply_official(None, OfficialEdition(year=2027, place="Kyoto")) is None
    out = apply_official(None, OfficialEdition(year=2027, date_text="August 17-22, 2027",
                                              start=date(2027, 8, 17), end=date(2027, 8, 22),
                                              place="Kyoto, Japan"))
    assert out.source == "official" and out.place == "Kyoto Japan"


def test_official_dates_clear_an_estimate():
    """추정 회차는 개최일이 비어 있을 때만 붙는다. 공식 개최일이 오면 추정 표시가 사라져야 한다."""
    est = Edition(year=2027, date_text="", start=None, end=None, place="", link=None,
                  deadlines=[], source="estimated", estimated_month=7)
    out = apply_official(est, OfficialEdition(year=2027, date_text="July 6-11, 2027",
                                             start=date(2027, 7, 6), end=date(2027, 7, 11)))
    assert out.estimated_month is None and out.start == date(2027, 7, 6)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_merge.py`
Expected: `ImportError: cannot import name 'apply_official'` (또는 `OfficialEdition`).

- [ ] **Step 3: 구현**

`scripts/models.py` 끝에 추가:

```python
@dataclass
class OfficialEdition:
    """공식 사이트에서 확인한 값 (설계 §8).

    회차를 통째로 대신하지 않고 merge.apply_official이 칸 단위로 덮는다.
    통째로 바꾸면 ai-deadlines가 준 리뷰 공개일 같은 세부 일정을 잃는다.
    """
    year: int
    date_text: str = ""
    start: date | None = None
    end: date | None = None
    place: str = ""
    deadlines: list[Deadline] = dc_field(default_factory=list)
```

`scripts/merge.py`의 models import를 바꾼다:

```python
from scripts.models import Deadline, Edition, OfficialEdition, normalize_place
```

`apply_scraped` 아래에 추가:

```python
# 공식 값이 오면 같은 타입의 기존 마감을 통째로 대신한다. 롤링 마감처럼 한
# 타입이 여러 번 나오므로 하나씩이 아니라 타입 단위로 바꾼다.
OFFICIAL_REPLACE_TYPES = frozenset({"paper", "short_paper", "abstract", "commitment", "poster", "lbw"})
# ai-deadlines는 commitment를 commitment_deadline이라는 이름으로 준다.
_REPLACE_ALIASES = {"commitment": {"commitment", "commitment_deadline"}}


def _same_entry(a: Deadline, b: Deadline) -> bool:
    return (a.type, a.date, (a.label or "").strip().lower()) == (
        b.type, b.date, (b.label or "").strip().lower())


def apply_official(edition: Edition | None, off: OfficialEdition) -> Edition | None:
    """공식 사이트에서 확인한 칸만 덮는다 (설계 §8).

    해당 연도 회차가 없으면 개최일이 있을 때만 새로 만든다.
    """
    if edition is None:
        if off.start is None:
            return None
        return Edition(
            year=off.year, date_text=off.date_text, start=off.start, end=off.end or off.start,
            place=off.place, link=None, deadlines=list(off.deadlines), source="official",
        )

    replaced: set[str] = set()
    for d in off.deadlines:
        if d.type in OFFICIAL_REPLACE_TYPES:
            replaced |= _REPLACE_ALIASES.get(d.type, {d.type})
    deadlines = [d for d in edition.deadlines if d.type not in replaced]
    for d in off.deadlines:
        if d.type in OFFICIAL_REPLACE_TYPES or not any(_same_entry(d, x) for x in deadlines):
            deadlines.append(d)

    out = replace(edition, deadlines=deadlines)
    if off.start:
        out.start, out.end = off.start, off.end or off.start
        out.date_text = off.date_text
        out.estimated_month = None
    if off.place:
        out.place = normalize_place(off.place)
    return out
```

- [ ] **Step 4: 통과와 판별 확인**

Run: `.venv/bin/python -m pytest -q`
Expected: 전체 통과 (Task 1 이후 개수 + 7).

판별 확인: `_REPLACE_ALIASES.get(d.type, {d.type})`를 `{d.type}`로 바꾸면 `test_official_commitment_replaces_ai_deadlines_commitment_deadline`이 실패해야 한다. `out.estimated_month = None`을 지우면 `test_official_dates_clear_an_estimate`가 실패해야 한다. 원복.

- [ ] **Step 5: 커밋**

```bash
git add scripts/models.py scripts/merge.py tests/test_merge.py
git commit -m "apply_official: 공식 값으로 확인된 칸만 덮는다

회차를 통째로 바꾸면 ai-deadlines가 준 세부 일정을 잃는다. 개최일·장소는
덮고, 마감은 타입 단위로 바꾸고, 워크숍 발표는 같은 것이 없을 때만 더한다.
해당 연도 회차가 없으면 개최일이 있을 때만 새로 만든다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
```

---

### Task 6: `official` 출처 읽기·쓰기와 빌드 적용

설계 §7 "통과한 값은 `data/official/<abbr>.yaml`에 쌓는다", §8 "적용 순서".

**Files:**
- Create: `scripts/sources/official.py`
- Modify: `scripts/build.py` (`build()` 시그니처, 적용 위치, `main()`)
- Modify: `.gitignore` (`data/official/raw/` 추가)
- Test: `tests/test_source_official.py`, `tests/test_build.py`

**Interfaces:**
- Consumes: Task 5의 `OfficialEdition`, `apply_official`, `OFFICIAL_REPLACE_TYPES`
- Produces:
  - `load_official(directory: Path) -> dict[tuple[str, int], OfficialEdition]` — `checklog.yaml`은 건너뛴다
  - `load_doc(path: Path) -> dict | None`
  - `merge_official_doc(doc: dict | None, key: str, year: int, approved: dict, checked: date) -> dict`
  - `write_official(path: Path, doc: dict) -> None`
  - `build(..., official: dict | None = None)` — 키는 결합 행이면 구성원 이름 소문자(`"iccv"`), 아니면 registry `abbr`(`"acl"`)
  - `scripts.build.OFFICIAL_DIR = ROOT / "data" / "official"`

- [ ] **Step 1: 실패 테스트 작성 — 읽기·쓰기**

`tests/test_source_official.py`:

```python
from datetime import date, datetime

from scripts.sources.official import load_official, merge_official_doc, write_official

APPROVED = {
    "edition": {"date_text": "August 17-22, 2027", "start": "2027-08-17", "end": "2027-08-22",
                "place": "Kyoto, Japan", "evidence": {"raw_text": "Kyoto, Japan August 17–22, 2027",
                                                       "url": "https://2027.aclweb.org/"}},
    "deadlines": [{"type": "paper", "label": "ARR submission deadline", "date": "2027-01-04 23:59:59",
                   "timezone": "AoE", "evidence": {"raw_text": "ARR ... January 4, 2027",
                                                    "url": "https://2027.aclweb.org/calls/main/"}}],
}


def test_roundtrip(tmp_path):
    doc = merge_official_doc(None, "acl", 2027, APPROVED, date(2026, 10, 12))
    write_official(tmp_path / "acl.yaml", doc)
    (tmp_path / "checklog.yaml").write_text("acl/2027: {}\n", encoding="utf-8")
    loaded = load_official(tmp_path)
    off = loaded[("acl", 2027)]
    assert off.start == date(2027, 8, 17) and off.place == "Kyoto, Japan"
    assert off.deadlines[0].date == datetime(2027, 1, 4, 23, 59, 59)
    assert off.deadlines[0].source == "official"
    assert off.deadlines[0].evidence["url"] == "https://2027.aclweb.org/calls/main/"
    assert len(loaded) == 1, "checklog.yaml은 출처가 아니다"


def test_later_run_keeps_what_it_did_not_recheck():
    """D 기준만 다시 본 주에 회차 정보가 빠졌다고 지우면 안 된다."""
    first = merge_official_doc(None, "acl", 2027, APPROVED, date(2026, 10, 12))
    commitment = {"edition": None, "deadlines": [{
        "type": "commitment", "label": "Commitment deadline", "date": "2027-03-01 23:59:59",
        "timezone": "AoE", "evidence": {"raw_text": "...", "url": "https://2027.aclweb.org/"}}]}
    second = merge_official_doc(first, "acl", 2027, commitment, date(2026, 10, 19))
    block = second["editions"][0]
    assert block["edition"]["start"] == "2027-08-17"
    assert sorted(d["type"] for d in block["deadlines"]) == ["commitment", "paper"]
    assert block["checked"] == "2026-10-19"


def test_new_value_of_same_type_replaces_old():
    first = merge_official_doc(None, "acl", 2027, APPROVED, date(2026, 10, 12))
    moved = {"edition": None, "deadlines": [{**APPROVED["deadlines"][0], "date": "2027-01-06 23:59:59"}]}
    second = merge_official_doc(first, "acl", 2027, moved, date(2026, 10, 19))
    assert [d["date"] for d in second["editions"][0]["deadlines"]] == ["2027-01-06 23:59:59"]
```

- [ ] **Step 2: 실패 테스트 작성 — 빌드**

`tests/test_build.py` 상단 import에 `from scripts.models import Deadline, Edition, OfficialEdition`(기존 줄 교체)을 반영하고 끝에 추가:

```python
def test_official_adds_deadline_to_upstream_edition():
    off = {("cvpr", 2026): OfficialEdition(year=2026, deadlines=[
        Deadline("commitment", "Commitment", datetime(2026, 1, 10, 23, 59, 59), "AoE", "official")])}
    out = build(REGISTRY, FIELDS, make_fetchers(hf={"cvpr": [cvpr_edition()]}), {}, {}, TODAY,
                official=off)
    cvpr = next(c for c in out["conferences"] if c["abbr"] == "CVPR")
    types = [d["type"] for e in cvpr["editions"] for d in e["deadlines"]]
    assert "commitment" in types and "paper" in types


def test_official_creates_missing_edition_with_dates():
    off = {("hri", 2026): OfficialEdition(year=2026, date_text="March 16-19, 2026",
                                          start=date(2026, 3, 16), end=date(2026, 3, 19),
                                          place="Edinburgh, Scotland")}
    out = build(REGISTRY, FIELDS, make_fetchers(), {}, {}, TODAY, official=off)
    hri = next(c for c in out["conferences"] if c["abbr"] == "HRI")
    assert hri["editions"][0]["place"] == "Edinburgh Scotland"
    assert hri["editions"][0]["source"] == "official"


COMBINED = {
    "abbr": "iccv/eccv", "display": "ICCV/ECCV", "full_name": "ICCV / ECCV",
    "grade": "최우수", "ai_specialist": True, "field": "CV", "homepage": None,
    "sources": {"ai_deadlines": None, "ccfddl": None},
    "members": [
        {"display": "ICCV", "homepage": None, "sources": {"ai_deadlines": "iccv", "ccfddl": None}},
        {"display": "ECCV", "homepage": None, "sources": {"ai_deadlines": "eccv", "ccfddl": None}},
    ],
}


def test_official_applies_to_combined_row_member():
    """Review Focus 5: 결합 행은 구성원 이름(iccv)으로 쌓인다."""
    iccv = Edition(year=2027, date_text="October 2-8, 2027", start=date(2027, 10, 2),
                   end=date(2027, 10, 8), place="Hong Kong China", link=None, deadlines=[],
                   source="ai-deadlines")
    off = {("iccv", 2027): OfficialEdition(year=2027, deadlines=[
        Deadline("paper", "Paper submission", datetime(2027, 3, 7, 23, 59, 59), "AoE", "official")])}
    out = build([COMBINED], FIELDS, make_fetchers(hf={"iccv": [iccv]}), {}, {}, TODAY, official=off)
    row = out["conferences"][0]
    assert row["abbr"] == "ICCV"
    assert [d["type"] for e in row["editions"] for d in e["deadlines"]] == ["paper"]
```

- [ ] **Step 3: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_source_official.py tests/test_build.py`
Expected: `ModuleNotFoundError: No module named 'scripts.sources.official'`, 빌드 테스트는 `TypeError: build() got an unexpected keyword argument 'official'`.

- [ ] **Step 4: 구현 — 읽기·쓰기**

`scripts/sources/official.py`:

```python
"""공식 사이트 확인 결과 (data/official/<key>.yaml, 설계 §7-§8).

검증 게이트와 독립 검토를 통과한 값만 들어 있다. 회차를 통째로 제공하지
않고 build.py가 이미 고른 회차 위에 칸 단위로 덮는다(merge.apply_official).
키는 결합 행이면 구성원 이름 소문자(iccv), 아니면 registry abbr(acl)다.
"""

from datetime import date
from pathlib import Path

import yaml

from scripts.merge import OFFICIAL_REPLACE_TYPES
from scripts.models import Deadline, OfficialEdition
from scripts.validate_scraped import _parse_datetime


def _to_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def load_doc(path: Path) -> dict | None:
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8")) or None


def load_official(directory: Path) -> dict[tuple[str, int], OfficialEdition]:
    out: dict[tuple[str, int], OfficialEdition] = {}
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.yaml")):
        if path.name == "checklog.yaml":
            continue
        doc = load_doc(path) or {}
        key = doc.get("abbr")
        if not key:
            continue
        for block in doc.get("editions") or []:
            year = int(block["year"])
            ed = block.get("edition") or {}
            deadlines = []
            for d in block.get("deadlines") or []:
                when = _parse_datetime(d.get("date"))
                if when is None:
                    continue
                deadlines.append(Deadline(
                    type=str(d["type"]), label=str(d.get("label") or d["type"]), date=when,
                    timezone=d.get("timezone"), source="official", evidence=d.get("evidence"),
                ))
            out[(str(key), year)] = OfficialEdition(
                year=year, date_text=str(ed.get("date_text") or ""),
                start=_to_date(ed.get("start")), end=_to_date(ed.get("end")),
                place=str(ed.get("place") or ""), deadlines=deadlines,
            )
    return out


def _entry_key(d: dict) -> tuple:
    if d["type"] in OFFICIAL_REPLACE_TYPES:
        return (d["type"],)
    return (d["type"], str(d["date"])[:10], str(d.get("label") or "").strip().lower())


def merge_official_doc(doc: dict | None, key: str, year: int, approved: dict, checked: date) -> dict:
    """이번 실행에서 통과한 값을 기존 문서에 합친다.

    이번에 다시 보지 않은 값은 지우지 않는다 - D 기준만 본 주에 회차 정보가
    빠졌다고 지우면 안 된다. 같은 타입의 새 값은 옛 값을 통째로 대신한다.
    """
    old_blocks = list((doc or {}).get("editions") or [])
    old = next((b for b in old_blocks if int(b["year"]) == year), {})
    others = [b for b in old_blocks if int(b["year"]) != year]

    new = list(approved.get("deadlines") or [])
    new_types = {d["type"] for d in new if d["type"] in OFFICIAL_REPLACE_TYPES}
    new_keys = {_entry_key(d) for d in new}
    kept = [d for d in old.get("deadlines") or []
            if d["type"] not in new_types and _entry_key(d) not in new_keys]

    block: dict = {"year": year, "checked": checked.isoformat()}
    edition = approved.get("edition") or old.get("edition")
    if edition:
        block["edition"] = edition
    block["deadlines"] = kept + new
    return {"abbr": key, "editions": sorted(others + [block], key=lambda b: int(b["year"]))}


def write_official(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
```

- [ ] **Step 5: 구현 — 빌드**

`scripts/build.py` import에 추가:

```python
from scripts.merge import apply_official, apply_scraped, merge_by_year, pick_member, select_editions
from scripts.sources.official import load_official
```
(기존 `from scripts.merge import ...` 줄을 이 줄로 교체.)

상수 추가 (`SCRAPED_DIR` 아래):

```python
OFFICIAL_DIR = ROOT / "data" / "official"
```

`_gather` 아래에 추가:

```python
def _apply_official_all(editions: list[Edition], official: dict, keys: tuple[str, str]) -> list[Edition]:
    """공식 사이트에서 확인한 칸을 덮는다. 구성원 이름, registry abbr 순서로 찾는다."""
    by_year = {e.year: e for e in editions}
    years = {year for (key, year) in official if key in keys}
    for year in years:
        off = official.get((keys[0], year)) or official.get((keys[1], year))
        updated = apply_official(by_year.get(year), off)
        if updated is not None:
            by_year[year] = updated
    return sorted(by_year.values(), key=lambda e: e.year)
```

`build()` 시그니처에 매개변수를 더한다:

```python
def build(
    registry: list[dict],
    fields: list[dict],
    fetchers: dict,
    manual: dict[str, list[Edition]],
    scraped: dict[tuple[str, int], list],
    today: date,
    official: dict | None = None,
) -> dict:
```

`selected = select_editions(editions, today)` 줄과 그 바로 아래 `member_key = display.lower()` 줄을 다음으로 바꾼다 (`member_key`를 위로 올리고 공식 값을 먼저 덮는다):

```python
        # 결합 행의 abbr_group("iccv/eccv")은 파일명이 될 수 없으므로 선택된
        # 구성원 이름으로 먼저 찾고, 비결합 행을 위해 abbr_group으로 폴백한다.
        member_key = display.lower()
        # 공식 값은 회차 선택 전에 덮는다 - 업스트림에 없던 회차를 공식 값이
        # 만들 수도 있고, 그 회차도 선택 대상이어야 한다 (설계 §8 적용 순서).
        editions = _apply_official_all(editions, official or {}, (member_key, abbr_group))
        selected = select_editions(editions, today)
```

`main()`의 `build(...)` 호출에 인자를 더한다:

```python
        scraped=load_scraped(SCRAPED_DIR),
        official=load_official(OFFICIAL_DIR),
        today=date.today(),
```

`.gitignore` 끝에 추가:

```
# 공식 사이트 확인의 실행별 작업 파일 (페이지 본문, 추출 JSON, 대상 목록)
data/official/raw/
```

- [ ] **Step 6: 통과와 판별 확인**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.build
git diff --stat docs/data/conferences.json
```
Expected: 전체 통과. `data/official/`이 아직 없으므로 `conferences.json`은 `generated_at` 외에 바뀌지 않는다.

판별 확인: `_apply_official_all` 호출 줄을 주석 처리하면 빌드 테스트 3개가 실패해야 한다. `merge_official_doc`의 `kept` 필터에서 `d["type"] not in new_types and`를 지우면 `test_new_value_of_same_type_replaces_old`가 실패해야 한다. 원복.

- [ ] **Step 7: 커밋**

```bash
git checkout docs/data/conferences.json
git add scripts/sources/official.py scripts/build.py .gitignore tests/test_source_official.py tests/test_build.py
git commit -m "official 출처: data/official/<key>.yaml을 회차 선택 전에 덮는다

공식 값이 업스트림에 없던 회차를 만들 수도 있어서 회차 선택보다 먼저
적용한다. 결합 행은 구성원 이름으로 찾는다. 이번 실행에서 다시 보지 않은
값은 문서에서 지우지 않는다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
```

---

### Task 7: 확인 기록과 대상 선정 (`checklog.py`, `gaps.py`)

설계 §4, §9.

**Files:**
- Create: `scripts/checklog.py`, `scripts/gaps.py`
- Test: `tests/test_checklog.py`, `tests/test_gaps.py`

**Interfaces:**
- Produces (`scripts/checklog.py`):
  - `load_checklog(path: Path) -> dict`, `save_checklog(path: Path, log: dict) -> None`
  - `entry_key(key: str, year: int) -> str` — `"acl/2027"`
  - `is_due(entry: dict | None, criterion: str, today: date, urgent: bool) -> bool`
  - `record(log: dict, key: str, year: int, today: date, criteria: list[str], results: dict[str, str], access: str, tba: list[str], urgent: bool) -> None`
- Produces (`scripts/gaps.py`):
  - `displayed_edition(editions: list[dict], today: date) -> dict | None` — `docs/lib.js` `pickEdition`과 같은 규칙
  - `official_key(conf: dict) -> str`
  - `triggered(edition: dict, today: date, entry: dict | None) -> list[str]`
  - `is_urgent(edition: dict, today: date) -> bool`
  - `select_targets(data: dict, log: dict, today: date, cap: int = 12) -> list[dict]` — 각 대상: `{"key", "abbr", "name", "year", "criteria": [str], "urgent": bool, "homepage", "edition_link", "conference_start"}`
  - `MAIN_TYPES: frozenset[str]`

- [ ] **Step 1: 실패 테스트 작성 — 확인 기록**

`tests/test_checklog.py`:

```python
from datetime import date

from scripts.checklog import entry_key, is_due, load_checklog, record, save_checklog

TODAY = date(2026, 10, 12)


def test_never_checked_is_due():
    assert is_due(None, "C", TODAY, urgent=False)


def test_weekly_criteria_come_back_after_seven_days():
    entry = {"last_checked": "2026-10-05", "results": {}}
    assert is_due(entry, "A", TODAY, urgent=False)
    assert not is_due({**entry, "last_checked": "2026-10-06"}, "A", TODAY, urgent=False)


def test_c_none_is_never_due_again_for_that_edition():
    """NeurIPS처럼 포스터 제출 트랙이 아예 없는 학회를 매주 읽지 않는다."""
    entry = {"last_checked": "2026-01-01", "results": {"C": "none"}}
    assert not is_due(entry, "C", TODAY, urgent=False)
    assert is_due({**entry, "results": {"C": "tba"}}, "C", TODAY, urgent=False)


def test_e_is_four_weekly_unless_a_deadline_is_near():
    entry = {"last_checked": "2026-09-28", "results": {"E": "found"}}
    assert not is_due(entry, "E", TODAY, urgent=False)
    assert is_due(entry, "E", TODAY, urgent=True)
    assert is_due({**entry, "last_checked": "2026-09-14"}, "E", TODAY, urgent=False)


def test_record_and_roundtrip(tmp_path):
    log = {}
    record(log, "acl", 2027, TODAY, ["D"], {"D": "tba"}, "ok", ["ARR commitment deadline"], False)
    path = tmp_path / "checklog.yaml"
    save_checklog(path, log)
    loaded = load_checklog(path)
    entry = loaded[entry_key("acl", 2027)]
    assert entry["last_checked"] == "2026-10-12"
    assert entry["next_due"] == "2026-10-19"
    assert entry["tba"] == ["ARR commitment deadline"]
```

- [ ] **Step 2: 실패 테스트 작성 — 대상 선정**

`tests/test_gaps.py`:

```python
from datetime import date

from scripts.gaps import displayed_edition, official_key, select_targets, triggered

TODAY = date(2026, 10, 12)


def ed(year, start=None, end=None, deadlines=(), source="ccfddl", link=None, **extra):
    return {"year": year, "start": start, "end": end or start, "deadlines": list(deadlines),
            "source": source, "link": link, "primary_deadline": None, **extra}


def dl(type_, date_, label="x"):
    return {"type": type_, "date": f"{date_}T23:59:59", "label": label}


def conf(abbr, editions, group=None, homepage="https://example.org/"):
    return {"abbr": abbr, "abbr_group": group or abbr.lower(), "full_name": abbr,
            "homepage": homepage, "editions": editions}


def test_a_estimated_edition():
    e = ed(2027, source="estimated", estimated_month=7)
    assert triggered(e, TODAY, None) == ["A"]


def test_b_no_main_deadline():
    e = ed(2027, "2027-06-01", deadlines=[dl("notification", "2027-03-01")])
    assert triggered(e, TODAY, None) == ["B"]


def test_c_paper_closed_and_nothing_else_before_the_conference():
    e = ed(2026, "2026-12-01", deadlines=[dl("paper", "2026-05-01")])
    assert triggered(e, TODAY, None) == ["C"]
    with_poster = ed(2026, "2026-12-01", deadlines=[dl("paper", "2026-05-01"), dl("poster", "2026-11-01")])
    assert triggered(with_poster, TODAY, None) == []
    with_ws = ed(2026, "2026-12-01", deadlines=[dl("paper", "2026-05-01"),
                                                 dl("notification", "2026-09-01", "Workshop acceptance")])
    assert triggered(with_ws, TODAY, None) == []


def test_d_open_tba_and_e_manual():
    e = ed(2027, "2027-08-17", deadlines=[dl("paper", "2027-01-04")], source="manual")
    assert triggered(e, TODAY, {"tba": ["commitment"]}) == ["D", "E"]


def test_displayed_edition_prefers_upcoming_then_estimate_then_latest_past():
    past = ed(2026, "2026-07-06", "2026-07-11")
    est = ed(2027, source="estimated", estimated_month=7)
    assert displayed_edition([past, est], TODAY)["year"] == 2027
    assert displayed_edition([past], TODAY)["year"] == 2026


def test_combined_row_uses_member_key():
    """Review Focus 5: 결합 행의 파일 키는 구성원 이름이다."""
    assert official_key(conf("ICCV", [], group="iccv/eccv")) == "iccv"
    assert official_key(conf("ACM MM", [], group="mm")) == "mm"


def test_order_cap_and_skip():
    data = {"conferences": [
        conf("C1", [ed(2026, "2026-12-01", deadlines=[dl("paper", "2026-05-01")])]),
        conf("A1", [ed(2027, source="estimated", estimated_month=7)]),
        conf("B1", [ed(2027, "2027-06-01")]),
        conf("OK", [ed(2027, "2027-06-01", deadlines=[dl("paper", "2027-01-01")])]),
    ]}
    targets = select_targets(data, {}, TODAY, cap=2)
    assert [t["abbr"] for t in targets] == ["A1", "B1"]
    assert targets[0]["key"] == "a1" and targets[0]["criteria"] == ["A"]


def test_recently_checked_target_is_skipped():
    data = {"conferences": [conf("B1", [ed(2027, "2027-06-01")])]}
    log = {"b1/2027": {"last_checked": "2026-10-10", "results": {"B": "none"}}}
    assert select_targets(data, log, TODAY) == []
```

- [ ] **Step 3: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_checklog.py tests/test_gaps.py`
Expected: `ModuleNotFoundError` 두 개.

- [ ] **Step 4: 구현 — 확인 기록**

`scripts/checklog.py`:

```python
"""공식 사이트 확인 기록 (data/official/checklog.yaml, 설계 §9).

시간이 아니라 이 기록으로 대상을 고르므로, 맥이 꺼져 한 주를 건너뛰어도
다음 실행이 밀린 대상을 그대로 이어받는다.
"""

from datetime import date, timedelta
from pathlib import Path

import yaml

WEEKLY = timedelta(days=7)
E_PERIOD = timedelta(days=28)


def load_checklog(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def save_checklog(path: Path, log: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(log, allow_unicode=True, sort_keys=True), encoding="utf-8")


def entry_key(key: str, year: int) -> str:
    return f"{key}/{year}"


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _period(criterion: str, urgent: bool) -> timedelta:
    return E_PERIOD if criterion == "E" and not urgent else WEEKLY


def is_due(entry: dict | None, criterion: str, today: date, urgent: bool) -> bool:
    """이 기준으로 이번 주에 다시 읽어야 하는가 (설계 §4 표)."""
    if not entry or not entry.get("last_checked"):
        return True
    if criterion == "C" and (entry.get("results") or {}).get("C") == "none":
        return False
    return _as_date(entry["last_checked"]) + _period(criterion, urgent) <= today


def record(log: dict, key: str, year: int, today: date, criteria: list[str],
           results: dict[str, str], access: str, tba: list[str], urgent: bool) -> None:
    dues = [today + _period(c, urgent) for c in criteria
            if not (c == "C" and results.get("C") == "none")]
    log[entry_key(key, year)] = {
        "last_checked": today.isoformat(),
        "access": access,
        "criteria": list(criteria),
        "results": dict(results),
        "tba": list(tba),
        "next_due": min(dues).isoformat() if dues else None,
    }
```

- [ ] **Step 5: 구현 — 대상 선정**

`scripts/gaps.py`:

```python
"""이번 주에 공식 사이트를 읽을 학회를 고른다 (설계 §4). LLM을 쓰지 않는다."""

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path

from scripts.checklog import entry_key, is_due, load_checklog

ROOT = Path(__file__).parents[1]
DATA_PATH = ROOT / "docs" / "data" / "conferences.json"
CHECKLOG_PATH = ROOT / "data" / "official" / "checklog.yaml"

CAP = 12
MAIN_TYPES = frozenset({"paper", "submission", "abstract", "short_paper", "commitment", "commitment_deadline"})
ORDER = ("A", "B", "D", "E_urgent", "E", "C")
URGENT = timedelta(days=30)


def _d(value) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def displayed_edition(editions: list[dict], today: date) -> dict | None:
    """docs/lib.js의 pickEdition과 같은 규칙. 화면에 뜨는 회차를 대상으로 삼는다."""
    if not editions:
        return None
    undated = lambda e: not (e.get("end") or e.get("start"))
    dated = [e for e in editions if not undated(e)]
    with_deadline = [e for e in editions if undated(e) and e.get("primary_deadline")]
    estimated = [e for e in editions if undated(e) and not e.get("primary_deadline") and e.get("estimated_month")]
    upcoming = []
    for e in dated:
        if _d(e.get("end") or e.get("start")) >= today:
            upcoming.append((_d(e.get("start") or e.get("end")), e))
    for e in with_deadline:
        if _d(e["primary_deadline"]) >= today:
            upcoming.append((_d(e["primary_deadline"]), e))
    for e in estimated:
        start = date(int(e["year"]), int(e["estimated_month"]), 1)
        if start >= today:
            upcoming.append((start, e))
    if upcoming:
        return min(upcoming, key=lambda t: t[0])[1]
    if dated:
        return max(dated, key=lambda e: _d(e.get("end") or e.get("start")))
    return editions[-1]


def official_key(conf: dict) -> str:
    """data/official/<key>.yaml의 키. 결합 행은 구성원 이름, 아니면 registry abbr."""
    group = conf.get("abbr_group") or conf["abbr"]
    return conf["abbr"].lower() if "/" in group else group


def _has_workshop_notification(deadlines: list[dict]) -> bool:
    return any(d["type"] == "notification" and re.search(r"workshop", d.get("label") or "", re.I)
               for d in deadlines)


def triggered(edition: dict, today: date, entry: dict | None) -> list[str]:
    """해당하는 기준 A-E. 재확인 주기는 따지지 않는다."""
    deadlines = edition.get("deadlines") or []
    out = []
    estimated = edition.get("source") == "estimated"
    if estimated or not (edition.get("start") or edition.get("end")):
        out.append("A")
    main = [d for d in deadlines if d["type"] in MAIN_TYPES]
    if not estimated and not main:
        out.append("B")
    start = _d(edition.get("start"))
    extra = any(d["type"] in ("poster", "lbw") for d in deadlines) or _has_workshop_notification(deadlines)
    if main and all(_d(d["date"]) < today for d in main) and start and start >= today and not extra:
        out.append("C")
    if entry and entry.get("tba"):
        out.append("D")
    if edition.get("source") == "manual":
        out.append("E")
    return out


def is_urgent(edition: dict, today: date) -> bool:
    return any(today <= _d(d["date"]) <= today + URGENT for d in edition.get("deadlines") or [])


def select_targets(data: dict, log: dict, today: date, cap: int = CAP) -> list[dict]:
    candidates = []
    for conf in data.get("conferences") or []:
        edition = displayed_edition(conf.get("editions") or [], today)
        if not edition:
            continue
        key = official_key(conf)
        entry = log.get(entry_key(key, edition["year"]))
        urgent = is_urgent(edition, today)
        due = [c for c in triggered(edition, today, entry) if is_due(entry, c, today, urgent)]
        if not due:
            continue
        labels = ["E_urgent" if (c == "E" and urgent) else c for c in due]
        rank = min(ORDER.index(label) for label in labels)
        last = _d(entry.get("last_checked")) if entry and entry.get("last_checked") else date.min
        candidates.append((rank, last, key, {
            "key": key, "abbr": conf["abbr"], "name": conf.get("full_name") or conf["abbr"],
            "year": int(edition["year"]), "criteria": due, "urgent": urgent,
            "homepage": conf.get("homepage"), "edition_link": edition.get("link"),
            "conference_start": edition.get("start"),
        }))
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    return [c[3] for c in candidates[:cap]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--today")
    parser.add_argument("--cap", type=int, default=CAP)
    args = parser.parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    targets = select_targets(data, load_checklog(CHECKLOG_PATH), today, args.cap)
    print(json.dumps(targets, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: 통과, 실데이터, 판별 확인**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.gaps --today 2026-10-12 --cap 50 | python3 -c "import json,sys; t=json.load(sys.stdin); print(len(t)); print(sorted({c for x in t for c in x['criteria']}))"
```
Expected: 전체 통과. 실데이터 대상은 2026-10-07 계산(29개)과 비슷한 수여야 한다. 크게 다르면 `triggered`가 설계 §4와 다르게 동작하는 것이니 원인을 찾는다 (Task 1 이후 `commitment`가 본 논문으로 바뀐 효과로 몇 개 줄 수는 있다).

판별 확인: `is_due`의 C-none 줄을 지우면 `test_c_none_is_never_due_again_for_that_edition`이, `official_key`의 `"/" in group` 분기를 지우면 `test_combined_row_uses_member_key`가 실패해야 한다. 원복.

- [ ] **Step 7: 커밋**

```bash
git add scripts/checklog.py scripts/gaps.py tests/test_checklog.py tests/test_gaps.py
git commit -m "대상 선정(A-E)과 확인 기록

정보가 부족한 학회만 고른다. A·B·D는 매주, C는 회차당 한 번 확인해 트랙이
없으면 다시 읽지 않고, E는 4주마다(마감 30일 이내면 매주). 한 번에 최대
12개. 시간이 아니라 확인 기록으로 고르므로 한 주를 건너뛰어도 이어받는다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
```

---

### Task 8: 3단계 페이지 수집 (`fetch_pages.py`)

설계 §6. 홈페이지와 회차 주소를 둘 다 받고, 받은 페이지 어디에도 대상 연도가 없으면 대체 주소가 필요하다고 표시한다.

**Files:**
- Create: `scripts/fetch_pages.py`
- Create: `tests/fixtures/official/acl-2027.txt`, `tests/fixtures/official/chi-2027.txt` (Step 6에서 실제 수집으로 만든다)
- Test: `tests/test_fetch_pages.py`

**Interfaces:**
- Consumes: Task 2의 `load_pages`(왕복 테스트용)
- Produces:
  - `FetchResult(key: str, year: int, access: str, pages: list[tuple[str, str]], attempts: list[dict], year_found: bool)` — `access`는 `ok | via_edition_link | via_alternate | needs_alternate | blocked`
  - `fetch_target(target: dict, fetch: Callable[[str], tuple[int | str, str | None]], extra_urls: Iterable[str] = ()) -> FetchResult`
  - `write_result(result: FetchResult, raw_dir: Path) -> None` — `<key>-<year>.txt`, `<key>-<year>.fetch.json`
  - `http_fetch(url: str) -> tuple[int | str, str | None]`
  - `is_allowed_url(url: str) -> bool`
  - 상수 `RAW_DIR = ROOT / "data" / "official" / "raw"`, `WORKLIST_PATH = RAW_DIR / "worklist.json"`
  - CLI: `python -m scripts.fetch_pages [--worklist PATH]` 또는 `--target KEY YEAR --urls URL...`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_fetch_pages.py`:

```python
from scripts.fetch_pages import FetchResult, fetch_target, is_allowed_url, write_result
from scripts.validate_official import load_pages


def page(body, links=()):
    anchors = "".join(f'<a href="{href}">{text}</a>' for href, text in links)
    return f"<html><head><title>T</title><script>var x=1;</script></head><body>{body}{anchors}</body></html>"


def fake(site):
    calls = []

    def fetch(url):
        calls.append(url)
        return site.get(url, (404, None))

    fetch.calls = calls
    return fetch


TARGET = {"key": "chi", "year": 2027, "homepage": "https://chi.acm.org/",
          "edition_link": "https://chi2027.acm.org/"}


def test_blocked_homepage_falls_back_to_edition_link():
    site = {
        "https://chi.acm.org/": (403, None),
        "https://chi2027.acm.org/": (200, page("CHI 2027 Pittsburgh", [("/authors/papers/", "Papers")])),
        "https://chi2027.acm.org/authors/papers/": (200, page("Paper submission deadline 10 September 2026")),
    }
    r = fetch_target(TARGET, fake(site))
    assert r.access == "via_edition_link"
    assert [u for u, _ in r.pages] == ["https://chi2027.acm.org/", "https://chi2027.acm.org/authors/papers/"]
    assert "var x" not in r.pages[0][1], "script는 버린다"


def test_open_homepage_without_target_year_needs_alternate():
    """ACL의 aclweb.org처럼 본부 사이트는 열리지만 그 연도 정보가 없다."""
    target = {"key": "acl", "year": 2027, "homepage": "https://www.aclweb.org/", "edition_link": None}
    site = {"https://www.aclweb.org/": (200, page("Association for Computational Linguistics 2025 news"))}
    r = fetch_target(target, fake(site))
    assert r.access == "needs_alternate" and not r.year_found


def test_both_homepage_and_edition_link_are_fetched():
    target = {"key": "acl", "year": 2027, "homepage": "https://www.aclweb.org/",
              "edition_link": "https://2027.aclweb.org/"}
    site = {"https://www.aclweb.org/": (200, page("ACL portal")),
            "https://2027.aclweb.org/": (200, page("ACL 2027 Kyoto"))}
    r = fetch_target(target, fake(site))
    assert r.access == "ok" and r.year_found


def test_crawl_follows_only_same_host_keyword_links_up_to_eight():
    links = [(f"/calls/p{i}/", "Call for Papers") for i in range(12)]
    links += [("https://other.org/dates/", "Important dates"), ("/about/", "About us"), ("/dates.pdf", "Dates")]
    site = {"https://chi2027.acm.org/": (200, page("CHI 2027", links))}
    for i in range(12):
        site[f"https://chi2027.acm.org/calls/p{i}/"] = (200, page(f"page {i} 2027"))
    fetch = fake(site)
    r = fetch_target({**TARGET, "homepage": None}, fetch)
    assert len(r.pages) == 8
    assert not any("other.org" in u or "about" in u or u.endswith(".pdf") for u in fetch.calls)


def test_alternate_urls_skip_aggregators():
    site = {"https://s2027.siggraph.org/": (200, page("SIGGRAPH 2027"))}
    fetch = fake(site)
    target = {"key": "siggraph", "year": 2027, "homepage": "https://www.siggraph.org/", "edition_link": None}
    r = fetch_target(target, fetch, ["https://ccfddl.com/conf/siggraph", "https://s2027.siggraph.org/"])
    assert r.access == "via_alternate"
    assert "https://ccfddl.com/conf/siggraph" not in fetch.calls


def test_alternate_that_still_lacks_the_year_is_blocked():
    site = {"https://x.org/": (200, page("nothing here"))}
    target = {"key": "x", "year": 2027, "homepage": None, "edition_link": None}
    assert fetch_target(target, fake(site), ["https://x.org/"]).access == "blocked"


def test_is_allowed_url():
    assert is_allowed_url("https://2027.aclweb.org/")
    assert not is_allowed_url("javascript:alert(1)")
    assert not is_allowed_url("https://huggingface.co/spaces/huggingface/ai-deadlines")
    assert not is_allowed_url("https://github.com/ccfddl/ccf-deadlines")


def test_write_result_roundtrips_through_load_pages(tmp_path):
    r = FetchResult("acl", 2027, "ok", [("https://a/", "alpha 2027"), ("https://b/", "beta")],
                    [{"url": "https://a/", "status": 200}], True)
    write_result(r, tmp_path)
    pages = load_pages((tmp_path / "acl-2027.txt").read_text(encoding="utf-8"))
    assert pages["https://a/"].strip() == "alpha 2027"
    assert (tmp_path / "acl-2027.fetch.json").exists()
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_fetch_pages.py`
Expected: `ModuleNotFoundError: No module named 'scripts.fetch_pages'`

- [ ] **Step 3: 구현**

`scripts/fetch_pages.py`:

```python
"""공식 사이트 페이지 수집 (설계 §6). LLM을 쓰지 않는다.

1 홈페이지와 2 회차 주소를 둘 다 받는다. 하나가 열렸다고 멈추지 않는다 -
ACL의 홈페이지 www.aclweb.org는 열리지만 2027 일정은 2027.aclweb.org에만
있다. 받은 페이지 어디에도 대상 연도가 없으면 needs_alternate로 표시하고,
3 Hermes가 찾은 대체 주소를 --urls로 받아 다시 수집한다.
"""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).parents[1]
RAW_DIR = ROOT / "data" / "official" / "raw"
WORKLIST_PATH = RAW_DIR / "worklist.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130 Safari/537.36")
MAX_PAGES = 8
REQUEST_GAP_SECONDS = 1.0
KEYWORDS = ("date", "deadline", "call", "cfp", "paper", "poster", "late-breaking", "lbw",
            "workshop", "important")
# 공식 사이트를 읽는 것이 목적이다. 마감 모음 사이트는 받지 않는다.
AGGREGATOR_HOSTS = ("ccfddl.com", "ccfddl.top", "ccfddl.github.io", "huggingface.co",
                    "aideadlin.es", "wikicfp.com", "conferenceindex.org", "github.com",
                    "raw.githubusercontent.com")
_SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".ics", ".css", ".js")
_HREF = re.compile(r"""<a\s[^>]*?href\s*=\s*["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)

Fetch = Callable[[str], tuple]


@dataclass
class FetchResult:
    key: str
    year: int
    access: str
    pages: list[tuple[str, str]]
    attempts: list[dict]
    year_found: bool


def html_to_text(html: str) -> str:
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html or "")
    t = re.sub(r"(?i)<br\s*/?>|</(p|li|h[1-6]|tr|div|section|td|th|dt|dd)>", "\n", t)
    t = unescape(re.sub(r"(?s)<[^>]+>", " ", t))
    lines = (" ".join(line.split()) for line in t.splitlines())
    return "\n".join(line for line in lines if line)


def extract_links(html: str, base: str) -> list[tuple[str, str]]:
    out = []
    for href, inner in _HREF.findall(html or ""):
        url = urljoin(base, href.strip()).split("#")[0]
        anchor = " ".join(re.sub(r"(?s)<[^>]+>", " ", unescape(inner)).split())
        out.append((url, anchor))
    return out


def is_allowed_url(url: str) -> bool:
    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not u.netloc:
        return False
    host = u.netloc.lower().split(":")[0]
    return not any(host == h or host.endswith("." + h) for h in AGGREGATOR_HOSTS)


def _wanted(url: str, anchor: str, host: str) -> bool:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or u.netloc != host:
        return False
    if u.path.lower().endswith(_SKIP_EXT):
        return False
    hay = (u.path + " " + anchor).lower()
    return any(k in hay for k in KEYWORDS)


def _dedupe(urls: Iterable[str]) -> list[str]:
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def crawl(start_urls: list[str], fetch: Fetch, max_pages: int = MAX_PAGES):
    queue, seen = list(start_urls), set()
    pages: list[tuple[str, str]] = []
    attempts: list[dict] = []
    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        status, html = fetch(url)
        attempts.append({"url": url, "status": status})
        if status != 200 or not html:
            continue
        pages.append((url, html_to_text(html)))
        host = urlparse(url).netloc
        for link, anchor in extract_links(html, url):
            if link not in seen and _wanted(link, anchor, host):
                queue.append(link)
    return pages, attempts


def fetch_target(target: dict, fetch: Fetch, extra_urls: Iterable[str] = ()) -> FetchResult:
    year = int(target["year"])
    has_year = lambda text: str(year) in text
    starts = _dedupe(u for u in (target.get("homepage"), target.get("edition_link"))
                     if u and is_allowed_url(u))
    pages, attempts = crawl(starts, fetch)
    extra = _dedupe(u for u in extra_urls if is_allowed_url(u))

    if extra:
        more, more_attempts = crawl(extra, fetch)
        attempts += more_attempts
        pages = (more + [p for p in pages if has_year(p[1])])[:MAX_PAGES]
        found = any(has_year(text) for _, text in pages)
        access = "via_alternate" if found else "blocked"
    else:
        found = any(has_year(text) for _, text in pages)
        home_ok = any(a["url"] == target.get("homepage") and a["status"] == 200 for a in attempts)
        if not found:
            access = "needs_alternate"
        elif home_ok:
            access = "ok"
        else:
            access = "via_edition_link"
    return FetchResult(str(target["key"]), year, access, pages, attempts, found)


def write_result(result: FetchResult, raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{result.key}-{result.year}"
    body = "".join(f"===== {url} =====\n{text}\n\n" for url, text in result.pages)
    (raw_dir / f"{stem}.txt").write_text(body, encoding="utf-8")
    meta = {"key": result.key, "year": result.year, "access": result.access,
            "year_found": result.year_found, "attempts": result.attempts}
    (raw_dir / f"{stem}.fetch.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def http_fetch(url: str):
    import requests

    time.sleep(REQUEST_GAP_SECONDS)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True)
    except requests.RequestException as exc:
        return type(exc).__name__, None
    if r.status_code != 200:
        return r.status_code, None
    if "html" not in r.headers.get("content-type", "") and "text" not in r.headers.get("content-type", ""):
        return "not_html", None
    return 200, r.text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worklist", type=Path, default=WORKLIST_PATH)
    parser.add_argument("--target", nargs=2, metavar=("KEY", "YEAR"))
    parser.add_argument("--urls", nargs="*", default=[])
    args = parser.parse_args()

    worklist = json.loads(args.worklist.read_text(encoding="utf-8"))
    if args.target:
        key, year = args.target[0], int(args.target[1])
        targets = [t for t in worklist if t["key"] == key and int(t["year"]) == year]
        if not targets:
            print(f"대상 목록에 없음: {key} {year}", file=sys.stderr)
            return 1
    else:
        targets = worklist

    summary = []
    for target in targets:
        result = fetch_target(target, http_fetch, args.urls if args.target else ())
        write_result(result, RAW_DIR)
        summary.append({"key": result.key, "year": result.year, "access": result.access,
                        "pages": len(result.pages)})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 통과와 판별 확인**

Run: `.venv/bin/python -m pytest -q tests/test_fetch_pages.py`
Expected: `8 passed`.

판별 확인: `starts`에서 `target.get("edition_link")`를 빼면 `test_blocked_homepage_falls_back_to_edition_link`와 `test_both_homepage_and_edition_link_are_fetched`가 실패해야 한다. `if not found: access = "needs_alternate"` 분기를 지우고 `home_ok`로만 판정하면 `test_open_homepage_without_target_year_needs_alternate`가 실패해야 한다. 원복.

- [ ] **Step 5: 실제 사이트로 수집 확인**

```bash
mkdir -p data/official/raw
cat > /tmp/wl.json <<'EOF'
[{"key": "acl", "year": 2027, "homepage": "https://www.aclweb.org/", "edition_link": "https://2027.aclweb.org/"},
 {"key": "chi", "year": 2027, "homepage": "https://chi.acm.org/", "edition_link": "https://chi2027.acm.org/"},
 {"key": "siggraph", "year": 2027, "homepage": "https://www.siggraph.org/", "edition_link": "https://www.siggraph.org/"}]
EOF
.venv/bin/python -m scripts.fetch_pages --worklist /tmp/wl.json
```
Expected: `acl` → `ok`, `chi` → `via_edition_link`, `siggraph` → `needs_alternate` (2026-10-07 조사: `www.siggraph.org`는 봇 확인 페이지). 그다음:

```bash
cp /tmp/wl.json data/official/raw/worklist.json
.venv/bin/python -m scripts.fetch_pages --target siggraph 2027 --urls https://s2027.siggraph.org/
```
Expected: `siggraph` → `via_alternate`. 결과가 다르면 원인을 찾아 고치고, 사이트 상태가 바뀐 것이면 그 사실을 구현 기록에 남긴다.

- [ ] **Step 6: 고정 입력 저장**

```bash
mkdir -p tests/fixtures/official
cp data/official/raw/acl-2027.txt tests/fixtures/official/acl-2027.txt
cp data/official/raw/chi-2027.txt tests/fixtures/official/chi-2027.txt
grep -c "^=====" tests/fixtures/official/acl-2027.txt tests/fixtures/official/chi-2027.txt
grep -l "ARR submission deadline" tests/fixtures/official/acl-2027.txt
grep -l "List of accepted workshops released" tests/fixtures/official/chi-2027.txt
```
Expected: 두 파일 모두 섹션이 2개 이상, 두 문장이 각각 들어 있다. ACL에 `/calls/main/` 페이지가, CHI에 `/authors/workshops/`와 `/authors/posters/` 페이지가 들어 있는지 `grep "^=====" ...`로 확인한다. 없으면 `KEYWORDS`를 점검한다.

- [ ] **Step 7: 커밋**

```bash
git add scripts/fetch_pages.py tests/test_fetch_pages.py tests/fixtures/official/acl-2027.txt tests/fixtures/official/chi-2027.txt
git commit -m "공식 사이트 3단계 수집: 홈페이지·회차 주소·대체 주소

홈페이지가 열려도 그 연도 정보가 없으면 멈추지 않는다 - ACL의
www.aclweb.org는 열리지만 2027 일정은 2027.aclweb.org에만 있다. 대체
주소는 Hermes가 찾고 수집은 스크립트가 한다. 마감 모음 사이트는 받지
않는다. ACL·CHI 2027 페이지를 테스트 고정 입력으로 저장.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
```

---

### Task 9: Claude 독립 검토 (`review_official.py`)

설계 §7a. 검토자에게 추출자의 답을 주지 않는다.

**Files:**
- Create: `scripts/review_official.py`
- Test: `tests/test_review_official.py`

**Interfaces:**
- Consumes: Task 2의 `squash`, `scripts.models.normalize_place`
- Produces:
  - `excerpt(page: str, raw: str, width: int = 1500) -> str`
  - `build_deadline_prompt(conference: str, year: int, url: str, page: str, raw: str, date_str: str) -> str`
  - `build_edition_prompt(conference: str, year: int, url: str, page: str, raw: str) -> str`
  - `parse_review(text: str) -> dict | None`
  - `deadline_mismatches(item: dict, review: dict, year: int) -> list[str]`, `edition_mismatches(edition: dict, review: dict, year: int) -> list[str]`
  - `ask_claude(prompt: str, timeout: int = 180) -> str`
  - `review(accepted: dict, pages: dict[str, str], conference: str, year: int, current: dict | None, ask=ask_claude) -> tuple[dict, list[dict]]` — `(approved, held)`. `approved`는 `accepted`와 같은 형식. `held` 항목: `{"item": dict, "review": dict | None, "reasons": [str]}`
  - `WHAT_FOR_TYPE: dict[str, set[str]]` — Task 12 역검증도 쓴다 (기존 scraped의 `workshop` 타입 포함)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_review_official.py`:

```python
import json

from scripts import review_official as ro

URL = "https://chi2027.acm.org/authors/workshops/"
PAGE = ("Workshops - ACM CHI 2027\n"
        "Thursday, October 1, 2026 : Organizer submission deadline\n"
        "Thursday, December 17, 2026 : List of accepted workshops released by workshop chairs\n")
NOTICE = {"type": "notification", "label": "LABEL-SENTINEL-XYZ", "date": "2026-12-17 23:59:59",
          "timezone": "AoE", "evidence": {"url": URL, "raw_text":
          "Thursday, December 17, 2026: List of accepted workshops released by workshop chairs"}}
AGREE = {"who_submits": "none", "what": "workshop_acceptance", "event_year": 2027,
         "exact": True, "date": "2026-12-17"}


def asker(*answers):
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        answer = answers[min(len(prompts), len(answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    ask.prompts = prompts
    return ask


def run(ask, current=None, deadlines=(NOTICE,)):
    accepted = {"edition": None, "deadlines": list(deadlines)}
    return ro.review(accepted, {URL: PAGE}, "CHI", 2027, current, ask=ask)


def test_agreement_is_approved():
    approved, held = run(asker(json.dumps(AGREE)))
    assert held == [] and approved["deadlines"] == [NOTICE]


def test_reviewer_never_sees_the_extractors_answer():
    ask = asker(json.dumps(AGREE))
    run(ask)
    assert "LABEL-SENTINEL-XYZ" not in ask.prompts[0]
    assert '"type": "notification"' not in ask.prompts[0]
    assert "List of accepted workshops released" in ask.prompts[0], "원문 발췌는 준다"


def test_disagreement_is_held_with_both_readings():
    ask = asker(json.dumps({**AGREE, "who_submits": "organizer", "what": "other"}))
    approved, held = run(ask)
    assert approved["deadlines"] == []
    assert held[0]["item"] == NOTICE and "what:other" in held[0]["reasons"]


def test_review_failure_holds_instead_of_applying():
    approved, held = run(asker(RuntimeError("login expired")))
    assert approved["deadlines"] == []
    assert held[0]["reasons"][0].startswith("review_failed")


def test_unparseable_review_is_held():
    _, held = run(asker("I think it is fine"))
    assert held[0]["reasons"] == ["unparseable_review"]


def test_unchanged_value_is_not_reviewed():
    ask = asker(json.dumps(AGREE))
    current = {"deadlines": [{"type": "notification", "date": "2026-12-17T23:59:59", "label": "x"}]}
    approved, held = run(ask, current=current)
    assert ask.prompts == [] and approved["deadlines"] == [NOTICE]


def test_poster_and_lbw_are_the_same_tier_and_workshop_paper_notification_counts():
    poster = {**NOTICE, "type": "poster"}
    review = {"who_submits": "author", "what": "lbw", "event_year": 2027, "exact": True, "date": "2026-12-17"}
    assert ro.deadline_mismatches(poster, review, 2027) == []
    wacv = {**NOTICE, "date": "2026-10-30 23:59:59"}
    review = {"who_submits": "none", "what": "workshop_paper_notification", "event_year": 2027,
              "exact": True, "date": "2026-10-30"}
    assert ro.deadline_mismatches(wacv, review, 2027) == []


def test_not_exact_and_wrong_year_are_mismatches():
    review = {**AGREE, "exact": False, "event_year": 2026}
    assert set(ro.deadline_mismatches(NOTICE, review, 2027)) == {"not_exact", "event_year:2026"}


def test_excerpt_finds_sentence_despite_whitespace():
    text = ro.excerpt(PAGE, "Thursday, December 17, 2026: List of accepted workshops")
    assert "December 17" in text


def test_claude_binary_falls_back_when_not_on_path(monkeypatch):
    monkeypatch.setattr(ro.shutil, "which", lambda name: None)
    assert ro.claude_bin().endswith("/.local/bin/claude")


def test_review_model_is_pinned(monkeypatch):
    """세션 기본값(Opus)을 따라가면 Pro 플랜에서 사용량이 커진다. 모델을 고정한다."""
    seen = {}

    class Done:
        returncode, stdout, stderr = 0, '{"result": "{}", "is_error": false}', ""

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return Done()

    monkeypatch.setattr(ro.subprocess, "run", fake_run)
    ro.ask_claude("q")
    assert seen["cmd"][seen["cmd"].index("--model") + 1] == ro.REVIEW_MODEL
    ro.ask_claude("q", model="claude-sonnet-5")
    assert "claude-sonnet-5" in seen["cmd"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_review_official.py`
Expected: `ImportError: cannot import name 'review_official'`

- [ ] **Step 3: 구현**

`scripts/review_official.py`:

```python
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
```

- [ ] **Step 4: 통과와 판별 확인**

Run: `.venv/bin/python -m pytest -q tests/test_review_official.py`
Expected: `11 passed`.

판별 확인: `build_deadline_prompt` 호출에 `item["label"]`을 `conference` 자리에 넣어 보면 `test_reviewer_never_sees_the_extractors_answer`가 실패해야 한다. `_ask`의 `except` 블록에서 `return {}, []`를 돌려주게 바꾸면 `test_review_failure_holds_instead_of_applying`이 실패해야 한다(빈 리뷰는 불일치로 잡히지만 사유가 `review_failed`로 시작하지 않는다). 원복.

- [ ] **Step 5: 실제 Claude 한 번 호출로 연결 확인**

```bash
.venv/bin/python - <<'EOF'
from scripts.review_official import ask_claude, parse_review, build_deadline_prompt
page = "Workshops - ACM CHI 2027\nThursday, December 17, 2026 : List of accepted workshops released by workshop chairs on the CHI website\n"
p = build_deadline_prompt("CHI", 2027, "https://chi2027.acm.org/authors/workshops/", page,
                          "Thursday, December 17, 2026 : List of accepted workshops released", "2026-12-17")
print(parse_review(ask_claude(p)))
EOF
```
Expected: `what`이 `workshop_acceptance`, `who_submits`가 `none`인 dict. 결과를 구현 기록에 남긴다 (판단은 Task 12에서 본격적으로 한다).

- [ ] **Step 6: 커밋**

```bash
git add scripts/review_official.py tests/test_review_official.py
git commit -m "반영 전 Claude 독립 검토

검토자에게 추출자의 type과 label을 주지 않고 원문 발췌만 준다. 두 해석이
같으면 반영, 다르거나 검토 호출이 실패하면 반영하지 않는다. 이미 같은 값이
실려 있으면 검토하지 않는다. cron 환경을 위해 claude 절대 경로로 폴백.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
```

---

### Task 10: 보고서와 디스코드 전송 (`report.py`)

설계 §10.

**Files:**
- Create: `scripts/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: Task 7의 `displayed_edition`
- Produces:
  - `RunResult` dataclass: `today: date`, `targets: list[dict]`, `applied: list[dict]`(`{"abbr","year","type","label","date","url"}`), `changes: list[dict]`, `rejected: list[dict]`(`{"abbr","year","item","reason"}`), `held: list[dict]`(`{"abbr","year","item","review","reasons"}`), `blocked: list[dict]`(`{"abbr","year"}`), `tba: list[dict]`(`{"abbr","year","items"}`), `failures: list[str]`, `upcoming: list[dict]`
  - `diff_conferences(before: dict, after: dict) -> list[dict]` — `{"abbr","year","field","old","new"}`
  - `featured_deadline(edition: dict, today: date) -> dict | None`, `upcoming_deadlines(data: dict, today: date, days: int = 14) -> list[dict]`
  - `render_report(run: RunResult) -> str`, `render_summary(run: RunResult) -> tuple[str, bool]` (텍스트, 잘렸는지)
  - `should_send(run: RunResult) -> bool`
  - `research_bin() -> str`, `send_discord(summary: str, report_path: Path, attach: bool, runner=subprocess.run) -> bool`
  - `REPORT_DIR = Path.home() / ".hermes" / "reports" / "conference-tracker"`, `write_report(run) -> Path`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_report.py`:

```python
from datetime import date
from pathlib import Path

from scripts import report as rp

TODAY = date(2026, 10, 12)


def data(*confs):
    return {"conferences": list(confs)}


def conf(abbr, deadlines, start="2027-08-17"):
    return {"abbr": abbr, "editions": [{"year": 2027, "start": start, "end": start,
                                        "date_text": "", "place": "P", "deadlines": deadlines}]}


def test_diff_reports_field_level_changes():
    before = data(conf("ACL", [{"type": "paper", "label": "ARR", "date": "2027-01-04T23:59:59"}]))
    after = data(conf("ACL", [{"type": "paper", "label": "ARR", "date": "2027-01-04T23:59:59"},
                              {"type": "commitment", "label": "Commitment", "date": "2027-03-01T23:59:59"}]))
    changes = rp.diff_conferences(before, after)
    assert changes == [{"abbr": "ACL", "year": 2027, "field": "commitment: Commitment",
                        "old": None, "new": "2027-03-01"}]


def test_featured_and_upcoming_follow_the_site_rules():
    """본 논문 → 포스터/LBW → 워크숍 발표 순서, AoE는 KST로 하루 뒤."""
    c = conf("CHI", [
        {"type": "paper", "label": "Papers", "date": "2026-09-10T23:59:59", "timezone": "AoE"},
        {"type": "notification", "label": "List of accepted workshops", "date": "2026-10-15T23:59:59", "timezone": "AoE"},
        {"type": "poster", "label": "Posters", "date": "2026-10-20T23:59:59", "timezone": "AoE"},
    ], start="2027-05-10")
    upcoming = rp.upcoming_deadlines(data(c), TODAY)
    assert upcoming == [{"abbr": "CHI", "label": "Posters", "date": "2026-10-21", "dday": 9}]


def make_run(**over):
    base = dict(today=TODAY, targets=[], applied=[], changes=[], rejected=[], held=[],
                blocked=[], tba=[], failures=[], upcoming=[])
    base.update(over)
    return rp.RunResult(**base)


def test_nothing_to_say_means_no_message():
    assert not rp.should_send(make_run(upcoming=[{"abbr": "X", "label": "y", "date": "z", "dday": 1}]))
    assert rp.should_send(make_run(blocked=[{"abbr": "SIGGRAPH", "year": 2027}]))
    assert rp.should_send(make_run(failures=["pytest 실패"]))


def test_summary_fits_discord_and_flags_truncation():
    held = [{"abbr": f"C{i}", "year": 2027, "item": {"type": "poster", "date": "2027-01-01 00:00:00",
             "label": "x" * 80}, "review": None, "reasons": ["what:other"]} for i in range(60)]
    text, truncated = rp.render_summary(make_run(held=held))
    assert len(text) <= 2000 and truncated
    short, cut = rp.render_summary(make_run(blocked=[{"abbr": "SIGGRAPH", "year": 2027}]))
    assert not cut and "SIGGRAPH" in short


def test_send_attaches_full_report_only_when_truncated(tmp_path):
    calls = []

    class Done:
        returncode = 0

    def runner(cmd, **kw):
        calls.append(cmd)
        return Done()

    assert rp.send_discord("요약", tmp_path / "r.md", attach=True, runner=runner)
    assert calls[0][1:4] == ["send", "-t", "discord"]
    assert calls[0][4].endswith(f"MEDIA:{tmp_path / 'r.md'}")
    rp.send_discord("요약", tmp_path / "r.md", attach=False, runner=runner)
    assert "MEDIA:" not in calls[1][4]


def test_research_binary_falls_back_when_not_on_path(monkeypatch):
    monkeypatch.setattr(rp.shutil, "which", lambda name: None)
    assert rp.research_bin().endswith("/.local/bin/research")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_report.py`
Expected: `ImportError`.

- [ ] **Step 3: 구현**

`scripts/report.py`:

```python
"""실행 보고서와 디스코드 전송 (설계 §10).

보내는 것은 스크립트가 만든 보고서다. Hermes의 마지막 응답을 그대로 보내지
않는다 - LLM이 요약하면서 반영 결과를 바꿔 말할 수 있기 때문이다.
"""

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from scripts.gaps import displayed_edition

REPORT_DIR = Path.home() / ".hermes" / "reports" / "conference-tracker"
DISCORD_LIMIT = 2000
_AOE = {"AoE", "AOE", "UTC-12"}
_PAPER = {"paper", "short_paper", "commitment", "commitment_deadline"}


@dataclass
class RunResult:
    today: date
    targets: list = field(default_factory=list)
    applied: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    held: list = field(default_factory=list)
    blocked: list = field(default_factory=list)
    tba: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    upcoming: list = field(default_factory=list)


def _index(data: dict) -> dict:
    out = {}
    for c in data.get("conferences") or []:
        for e in c.get("editions") or []:
            base = (c["abbr"], e["year"])
            out[base + ("개최일",)] = e.get("date_text") or ""
            out[base + ("장소",)] = e.get("place") or ""
            for d in e.get("deadlines") or []:
                out[base + (f"{d['type']}: {d.get('label') or ''}",)] = str(d["date"])[:10]
    return out


def diff_conferences(before: dict, after: dict) -> list[dict]:
    b, a = _index(before), _index(after)
    return [{"abbr": k[0], "year": k[1], "field": k[2], "old": b.get(k), "new": a.get(k)}
            for k in sorted(set(b) | set(a), key=str) if b.get(k) != a.get(k)]


def _kst_date(d: dict) -> date:
    when = datetime.fromisoformat(str(d["date"])[:19])
    if str(d.get("timezone") or "") in _AOE:
        when += timedelta(hours=21)  # AoE(UTC-12) -> KST(UTC+9)
    return when.date()


def featured_deadline(edition: dict, today: date) -> dict | None:
    """화면의 대표 마감과 같은 순서: 본 논문(앞선 초록 포함) → 포스터/LBW → 워크숍 발표."""
    dl = edition.get("deadlines") or []
    open_ = lambda ds: [d for d in ds if _kst_date(d) >= today]
    papers = [d for d in dl if d["type"] in _PAPER] or [d for d in dl if d["type"] == "submission"]
    main_open = open_(papers)
    if main_open:
        first = min(_kst_date(d) for d in main_open)
        abstracts = [d for d in open_([d for d in dl if d["type"] == "abstract"]) if _kst_date(d) <= first]
        pool = abstracts or main_open
    else:
        pool = open_([d for d in dl if d["type"] in ("poster", "lbw")]) or open_(
            [d for d in dl if d["type"] == "notification" and re.search(r"workshop", d.get("label") or "", re.I)])
    return min(pool, key=_kst_date) if pool else None


def upcoming_deadlines(data: dict, today: date, days: int = 14) -> list[dict]:
    out = []
    for c in data.get("conferences") or []:
        edition = displayed_edition(c.get("editions") or [], today)
        chosen = featured_deadline(edition, today) if edition else None
        if not chosen:
            continue
        dday = (_kst_date(chosen) - today).days
        if 0 <= dday <= days:
            out.append({"abbr": c["abbr"], "label": chosen.get("label") or chosen["type"],
                        "date": _kst_date(chosen).isoformat(), "dday": dday})
    return sorted(out, key=lambda x: (x["dday"], x["abbr"]))


def should_send(run: RunResult) -> bool:
    return bool(run.changes or run.applied or run.held or run.rejected or run.blocked or run.failures)


def _lines(run: RunResult) -> list[str]:
    lines = [f"📅 ConferenceTracker 공식 사이트 확인 ({run.today.isoformat()})",
             f"대상 {len(run.targets)} · 반영 {len(run.applied)} · 보류 {len(run.held)} · "
             f"탈락 {len(run.rejected)} · 접속 실패 {len(run.blocked)}"]
    if run.failures:
        lines += ["", "[실패]"] + [f"- {f}" for f in run.failures]
    if run.applied:
        lines += ["", "[반영]"] + [f"- {a['abbr']} {a['year']} {a['label']}: {a['date'][:10]} <{a['url']}>"
                                   for a in run.applied]
    if run.held:
        lines += ["", "[보류: 해석 불일치 - 확인 필요]"] + [
            f"- {h['abbr']} {h['year']} {h['item'].get('type')} {str(h['item'].get('date', ''))[:10]}"
            f" {h['item'].get('label', '')}: {', '.join(h['reasons'])}" for h in run.held]
    if run.rejected:
        lines += ["", "[게이트 탈락]"] + [f"- {r['abbr']} {r['year']} {r['item'].get('type')}: {r['reason']}"
                                       for r in run.rejected]
    if run.blocked:
        lines += ["", "[접속 실패]"] + [f"- {b['abbr']} {b['year']}" for b in run.blocked]
    if run.tba:
        lines += ["", "[아직 미공개]"] + [f"- {t['abbr']} {t['year']}: {'; '.join(t['items'])}" for t in run.tba]
    if run.upcoming:
        lines += ["", "[14일 안 마감]"] + [f"- D-{u['dday']} {u['abbr']} {u['label']} ({u['date']})"
                                         for u in run.upcoming]
    return lines


def render_summary(run: RunResult) -> tuple[str, bool]:
    text = "\n".join(_lines(run))
    if len(text) <= DISCORD_LIMIT:
        return text, False
    tail = "\n… (전체 보고서 첨부)"
    return text[: DISCORD_LIMIT - len(tail) - 60].rsplit("\n", 1)[0] + tail, True


def render_report(run: RunResult) -> str:
    lines = _lines(run)
    if run.changes:
        lines += ["", "[사이트 값 변경 (이전 → 새 값)]"] + [
            f"- {c['abbr']} {c['year']} {c['field']}: {c['old']} → {c['new']}" for c in run.changes]
    if run.held:
        lines += ["", "[보류 항목 상세]"]
        for h in run.held:
            lines += [f"- {h['abbr']} {h['year']}", f"  추출: {h['item']}", f"  검토: {h['review']}"]
    return "\n".join(lines) + "\n"


def write_report(run: RunResult) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{run.today.isoformat()}.md"
    path.write_text(render_report(run), encoding="utf-8")
    return path


def research_bin() -> str:
    # cron 환경에는 ~/.local/bin이 PATH에 없을 수 있다.
    return shutil.which("research") or str(Path.home() / ".local" / "bin" / "research")


def send_discord(summary: str, report_path: Path, attach: bool, runner=subprocess.run) -> bool:
    message = summary + (f"\nMEDIA:{report_path}" if attach else "")
    proc = runner([research_bin(), "send", "-t", "discord", message],
                  capture_output=True, text=True, timeout=60)
    return proc.returncode == 0
```

- [ ] **Step 4: 통과와 판별 확인**

Run: `.venv/bin/python -m pytest -q tests/test_report.py`
Expected: `6 passed`.

판별 확인: `featured_deadline`의 `pool = ... or open_(notification...)` 순서를 바꿔 워크숍 발표를 먼저 보게 하면 `test_featured_and_upcoming_follow_the_site_rules`가 실패해야 한다. `_kst_date`의 `+= timedelta(hours=21)`를 지우면 같은 테스트의 날짜가 `2026-10-20`이 되어 실패해야 한다. 원복.

- [ ] **Step 5: 커밋**

```bash
git add scripts/report.py tests/test_report.py
git commit -m "주간 확인 보고서와 디스코드 전송

스크립트가 만든 보고서를 research 프로필의 디스코드 기본 채널로 보낸다.
2,000자를 넘으면 요약만 보내고 전체 보고서를 첨부한다. 바뀐 것도 실패도
없으면 보내지 않는다. 14일 안 마감은 화면의 대표 마감 규칙을 따른다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
```

---

### Task 11: 오케스트레이션, Hermes 지시문, 끝단 테스트

설계 §5, §11.

**Files:**
- Create: `scripts/official_run.py`, `docs/hermes/official-check.md`, `scripts/hermes_prep.sh`
- Create: `tests/fixtures/official/acl-2027.extraction.json`, `tests/fixtures/official/chi-2027.extraction.json`
- Test: `tests/test_official_run.py`

**Interfaces:**
- Consumes: Task 2–10의 모든 공개 함수
- Produces:
  - `TargetOutcome(key, year, access, approved=None, rejected=[], held=[], tba=[], no_track=[], error=None)`
  - `process_target(target: dict, raw_dir: Path, data: dict, ask) -> TargetOutcome`
  - `results_for(target: dict, outcome: TargetOutcome) -> dict[str, str]`
  - `prep_run(today: date, run=_run, fetch=http_fetch) -> int`
  - `apply_run(today: date, ask=ask_claude, run=_run, send=send_discord, push: bool = True, notify: bool = True) -> int`
  - CLI: `python -m scripts.official_run prep|apply [--today YYYY-MM-DD] [--no-push] [--no-send]`

- [ ] **Step 1: 고정 추출 JSON 만들기**

Task 8의 고정 입력에서 실제 문장을 확인하고 그대로 옮긴다:

```bash
grep -n "ARR submission deadline" tests/fixtures/official/acl-2027.txt | head -3
grep -n "^=====" tests/fixtures/official/acl-2027.txt
grep -n "List of accepted workshops released\|Organizer submission deadline" tests/fixtures/official/chi-2027.txt
grep -n "^=====" tests/fixtures/official/chi-2027.txt
```

`tests/fixtures/official/acl-2027.extraction.json` — `raw_text`는 위 grep 결과의 문장을 그대로, `url`은 그 문장이 든 섹션의 주소로:

```json
{"abbr": "acl", "year": 2027,
 "edition": null,
 "items": [{"type": "paper", "label": "ARR submission deadline (long & short papers)",
            "date": "2027-01-04 23:59:59", "timezone": "AoE", "confidence": "high",
            "raw_text": "<grep으로 확인한 문장>", "url": "<그 문장이 든 섹션 주소>"}],
 "not_published": ["ARR commitment deadline: TBA"], "no_track": []}
```

`tests/fixtures/official/chi-2027.extraction.json`:

```json
{"abbr": "chi", "year": 2027, "edition": null,
 "items": [
   {"type": "notification", "label": "List of accepted workshops released", "date": "2026-12-17 23:59:59",
    "timezone": "AoE", "confidence": "high", "raw_text": "<grep: Thursday, December 17, 2026 ... List of accepted workshops released ...>",
    "url": "https://chi2027.acm.org/authors/workshops/"},
   {"type": "poster", "label": "Workshops", "date": "2026-10-01 23:59:59",
    "timezone": "AoE", "confidence": "high", "raw_text": "<grep: Thursday, October 1, 2026 ... Organizer submission deadline>",
    "url": "https://chi2027.acm.org/authors/workshops/"}],
 "not_published": [], "no_track": []}
```
`<...>` 자리를 실제 문장과 주소로 채운다. 두 번째 항목은 2026-09의 CHI 오류를 재현한 것으로, 해석 규칙(금지어)에서 떨어져야 한다.

`timezone: "AoE"`는 게이트 3이 **인용문이 든 그 섹션**에서 AoE 표기를 찾는다. 섹션마다 확인한다:

```bash
.venv/bin/python - <<'EOF'
from scripts.validate_official import load_pages, AOE_RE
for f in ("acl", "chi"):
    pages = load_pages(open(f"tests/fixtures/official/{f}-2027.txt", encoding="utf-8").read())
    for url, body in pages.items():
        print(f, bool(AOE_RE.search(body)), url)
EOF
```
인용할 섹션에 AoE 표기가 없으면, 같은 날짜가 AoE 표기와 함께 실린 다른 섹션(예: ACL 홈페이지의 Important Dates)의 문장을 쓴다.

- [ ] **Step 2: 실패 테스트 작성**

`tests/test_official_run.py`:

```python
import json
import shutil
from datetime import date
from pathlib import Path

from scripts import official_run as orun

FIX = Path(__file__).parent / "fixtures" / "official"
TODAY = date(2026, 10, 12)


def agree_with(item_type_to_answer):
    def ask(prompt):
        for marker, answer in item_type_to_answer:
            if marker in prompt:
                return json.dumps(answer)
        return json.dumps({"who_submits": "none", "what": "other", "event_year": 0, "exact": False, "date": ""})
    return ask


ACL_PAPER = ("ARR submission deadline", {"who_submits": "author", "what": "paper", "event_year": 2027,
                                          "exact": True, "date": "2027-01-04"})
CHI_LIST = ("List of accepted workshops", {"who_submits": "none", "what": "workshop_acceptance",
                                            "event_year": 2027, "exact": True, "date": "2026-12-17"})


def stage(tmp_path, key, access="ok"):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    shutil.copy(FIX / f"{key}-2027.txt", raw / f"{key}-2027.txt")
    shutil.copy(FIX / f"{key}-2027.extraction.json", raw / f"{key}-2027.json")
    (raw / f"{key}-2027.fetch.json").write_text(json.dumps({"access": access}), encoding="utf-8")
    return raw


def target(key, criteria):
    return {"key": key, "abbr": key.upper(), "name": key.upper(), "year": 2027, "criteria": criteria,
            "urgent": False, "homepage": None, "edition_link": None, "conference_start": None}


def test_acl_end_to_end_without_llm(tmp_path):
    raw = stage(tmp_path, "acl")
    o = orun.process_target(target("acl", ["D"]), raw, {"conferences": []}, agree_with([ACL_PAPER]))
    assert o.error is None and o.held == [] and o.rejected == []
    assert [d["type"] for d in o.approved["deadlines"]] == ["paper"]
    assert orun.results_for(target("acl", ["D"]), o) == {"D": "tba"}


def test_chi_proposal_is_caught_and_list_release_passes(tmp_path):
    raw = stage(tmp_path, "chi")
    o = orun.process_target(target("chi", ["C"]), raw, {"conferences": []}, agree_with([CHI_LIST]))
    assert [d["type"] for d in o.approved["deadlines"]] == ["notification"]
    assert [r["reject_reason"] for r in o.rejected] == ["forbidden_word"]
    assert orun.results_for(target("chi", ["C"]), o) == {"C": "found"}


def test_blocked_and_missing_extraction(tmp_path):
    raw = stage(tmp_path, "acl", access="needs_alternate")
    assert orun.process_target(target("acl", ["A"]), raw, {"conferences": []}, None).access == "blocked"
    raw = stage(tmp_path, "chi")
    (raw / "chi-2027.json").unlink()
    assert orun.process_target(target("chi", ["C"]), raw, {"conferences": []}, None).error == "추출 결과 없음"


class Proc:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def wire(monkeypatch, tmp_path, script):
    """apply_run이 쓰는 경로를 tmp로 돌리고, 명령 실행을 script(cmd)->Proc로 바꾼다."""
    raw = stage(tmp_path, "acl")
    (raw / "worklist.json").write_text(json.dumps([target("acl", ["D"])]), encoding="utf-8")
    data_path = tmp_path / "conferences.json"
    data_path.write_text(json.dumps({"conferences": []}), encoding="utf-8")
    monkeypatch.setattr(orun, "RAW_DIR", raw)
    monkeypatch.setattr(orun, "WORKLIST_PATH", raw / "worklist.json")
    monkeypatch.setattr(orun, "DATA_PATH", data_path)
    monkeypatch.setattr(orun, "OFFICIAL_DIR", tmp_path / "official")
    monkeypatch.setattr(orun, "CHECKLOG_PATH", tmp_path / "official" / "checklog.yaml")
    monkeypatch.setattr(orun, "write_report", lambda run: tmp_path / "report.md")
    calls = []

    def run(cmd):
        calls.append(cmd)
        return script(cmd)

    return run, calls


def test_apply_writes_official_and_checklog_then_pushes(monkeypatch, tmp_path):
    run, calls = wire(monkeypatch, tmp_path, lambda cmd: Proc(1 if cmd[:3] == ["git", "diff", "--cached"] else 0))
    sent = []
    code = orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run,
                          send=lambda s, p, a: sent.append(s) or True)
    assert code == 0
    assert (tmp_path / "official" / "acl.yaml").exists()
    assert "acl/2027" in (tmp_path / "official" / "checklog.yaml").read_text(encoding="utf-8")
    assert ["git", "push", "origin", "HEAD:master"] in calls
    assert sent, "반영이 있으면 알린다"


def test_failed_tests_block_push_and_stash(monkeypatch, tmp_path):
    def script(cmd):
        return Proc(1, err="1 failed") if "pytest" in cmd else Proc(0)
    run, calls = wire(monkeypatch, tmp_path, script)
    sent = []
    code = orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run,
                          send=lambda s, p, a: sent.append(s) or True)
    assert code == 1
    assert not any(c[:2] == ["git", "push"] for c in calls)
    assert any(c[:3] == ["git", "stash", "push"] for c in calls)
    assert "Python 테스트 실패" in sent[0]


def test_push_conflict_rebuilds_instead_of_merging(monkeypatch, tmp_path):
    """Review Focus 4: Actions가 그 사이 conferences.json을 바꿨을 때."""
    state = {"push": 0}

    def script(cmd):
        if cmd[:3] == ["git", "diff", "--cached"]:
            return Proc(1)
        if cmd[:2] == ["git", "push"]:
            state["push"] += 1
            return Proc(1 if state["push"] == 1 else 0)
        if cmd[:2] == ["git", "rebase"] and cmd[2:] == ["origin/master"]:
            return Proc(1, err="CONFLICT docs/data/conferences.json")
        return Proc(0)

    run, calls = wire(monkeypatch, tmp_path, script)
    code = orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run, send=lambda s, p, a: True)
    assert code == 0
    i = calls.index(["git", "rebase", "--abort"])
    after = calls[i:]
    assert ["git", "reset", "--hard", "origin/master"] in after
    assert any("scripts.build" in " ".join(c) for c in after), "다시 빌드한다"
    assert not any(c[:2] == ["git", "checkout"] and "--theirs" in c for c in calls), "손 병합 금지"
```

- [ ] **Step 3: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_official_run.py`
Expected: `ImportError: cannot import name 'official_run'`

- [ ] **Step 4: 구현 — 오케스트레이터**

`scripts/official_run.py`:

```python
"""공식 사이트 주간 확인의 두 단계 (설계 §5).

prep  : 대상 선정 → 페이지 수집 → Hermes에게 넘길 목록 출력 (cron 사전 스크립트)
apply : 검증 → 독립 검토 → 공식 값 기록 → 빌드·테스트 → 커밋·push → 보고·알림
Hermes는 두 단계 사이에서 추출 JSON을 쓰는 일만 한다.
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from scripts.checklog import load_checklog, record, save_checklog
from scripts.fetch_pages import fetch_target, http_fetch, write_result
from scripts.gaps import official_key, select_targets
from scripts.report import (
    RunResult, diff_conferences, render_summary, send_discord, should_send,
    upcoming_deadlines, write_report,
)
from scripts.review_official import ask_claude, review
from scripts.sources.official import load_doc, merge_official_doc, write_official
from scripts.validate_official import CORE_TYPES, load_pages, validate_official

ROOT = Path(__file__).parents[1]
DATA_PATH = ROOT / "docs" / "data" / "conferences.json"
OFFICIAL_DIR = ROOT / "data" / "official"
CHECKLOG_PATH = OFFICIAL_DIR / "checklog.yaml"
RAW_DIR = OFFICIAL_DIR / "raw"
WORKLIST_PATH = RAW_DIR / "worklist.json"
PY = sys.executable

BUILD_STEPS = [
    ("빌드", [PY, "-m", "scripts.build"]),
    ("정적 자원 도장", [PY, "scripts/stamp_assets.py"]),
    ("Python 테스트", [PY, "-m", "pytest", "-q"]),
    ("JS 테스트", ["node", "--test", "tests/js/"]),
]
COMMIT_PATHS = ["data/official", "docs/data/conferences.json", "docs/index.html", "docs/app.js"]
BOT = ["-c", "user.name=conference-tracker[hermes]", "-c", "user.email=junn103.jeon@gmail.com"]


@dataclass
class TargetOutcome:
    key: str
    year: int
    access: str
    approved: dict | None = None
    rejected: list = field(default_factory=list)
    held: list = field(default_factory=list)
    tba: list = field(default_factory=list)
    no_track: list = field(default_factory=list)
    error: str | None = None


def _run(cmd: list[str]):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)


def current_edition(data: dict, key: str, year: int) -> dict | None:
    for conf in data.get("conferences") or []:
        if official_key(conf) == key:
            return next((e for e in conf.get("editions") or [] if int(e["year"]) == year), None)
    return None


def process_target(target: dict, raw_dir: Path, data: dict, ask) -> TargetOutcome:
    key, year = target["key"], int(target["year"])
    fetch_path = raw_dir / f"{key}-{year}.fetch.json"
    access = json.loads(fetch_path.read_text(encoding="utf-8"))["access"] if fetch_path.exists() else "blocked"
    if access in ("needs_alternate", "blocked"):
        return TargetOutcome(key, year, "blocked")
    extraction_path = raw_dir / f"{key}-{year}.json"
    if not extraction_path.exists():
        return TargetOutcome(key, year, access, error="추출 결과 없음")
    try:
        extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return TargetOutcome(key, year, access, error=f"추출 JSON 형식 오류: {exc}")
    if int(extraction.get("year", 0)) != year:
        return TargetOutcome(key, year, access, error="추출 JSON의 연도가 대상과 다름")

    pages = load_pages((raw_dir / f"{key}-{year}.txt").read_text(encoding="utf-8"))
    current = current_edition(data, key, year)
    start = date.fromisoformat(str(current["start"])[:10]) if current and current.get("start") else None
    accepted, rejected = validate_official(extraction, pages, start)
    approved, held = review(accepted, pages, target["name"], year, current, ask=ask)
    return TargetOutcome(key, year, access, approved, rejected, held,
                         list(extraction.get("not_published") or []),
                         list(extraction.get("no_track") or []))


def results_for(target: dict, o: TargetOutcome) -> dict[str, str]:
    if o.access == "blocked":
        return {c: "blocked" for c in target["criteria"]}
    approved = o.approved or {"edition": None, "deadlines": []}
    types = {d["type"] for d in approved["deadlines"]}
    out = {}
    for c in target["criteria"]:
        if c == "A":
            out[c] = "found" if approved["edition"] else ("tba" if o.tba else "none")
        elif c == "B":
            out[c] = "found" if types & CORE_TYPES else ("tba" if o.tba else "none")
        elif c == "C":
            if types & {"poster", "lbw", "notification"}:
                out[c] = "found"
            elif {"poster", "lbw", "workshop"} <= set(o.no_track):
                out[c] = "none"
            else:
                out[c] = "tba"
        elif c == "D":
            out[c] = "tba" if o.tba else "found"
        else:
            out[c] = "found"
    return out


def _rebuild_and_test(run, result: RunResult) -> bool:
    for name, cmd in BUILD_STEPS:
        proc = run(cmd)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[-300:]
            result.failures.append(f"{name} 실패: {detail}")
            return False
    return True


def _commit(run, message: str) -> bool:
    run(["git", "add", *COMMIT_PATHS])
    if run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return False
    run(["git", *BOT, "commit", "-m", message])
    return True


def _commit_and_push(run, result: RunResult, today: date) -> None:
    message = (f"공식 사이트 주간 확인 ({today.isoformat()})\n\n"
               f"반영 {len(result.applied)}건, 보류 {len(result.held)}건, "
               f"탈락 {len(result.rejected)}건, 접속 실패 {len(result.blocked)}건.")
    if not _commit(run, message):
        return
    for _ in range(3):
        if run(["git", "push", "origin", "HEAD:master"]).returncode == 0:
            return
        run(["git", "fetch", "origin"])
        if run(["git", "rebase", "origin/master"]).returncode == 0:
            continue
        # conferences.json 같은 파생 파일 충돌이다. 손으로 병합하지 않는다 -
        # 우리 입력(data/official)만 살려 원격 위에서 다시 빌드한다 (설계 §11).
        run(["git", "rebase", "--abort"])
        run(["git", "stash", "push", "-u", "-m", "official-check push 재시도", "--", "data/official"])
        run(["git", "reset", "--hard", "origin/master"])
        run(["git", "stash", "pop"])
        if not _rebuild_and_test(run, result):
            return
        _commit(run, message)
    result.failures.append("push 실패 (3회 시도)")


def apply_run(today: date, ask=ask_claude, run=_run, send=send_discord,
              push: bool = True, notify: bool = True) -> int:
    worklist = json.loads(WORKLIST_PATH.read_text(encoding="utf-8"))
    before = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    log = load_checklog(CHECKLOG_PATH)
    result = RunResult(today=today, targets=worklist)

    for t in worklist:
        o = process_target(t, RAW_DIR, before, ask)
        label = {"abbr": t["abbr"], "year": t["year"]}
        if o.error:
            result.failures.append(f"{t['abbr']} {t['year']}: {o.error}")
            continue  # 기록을 갱신하지 않으므로 다음 주에 다시 본다
        if o.access == "blocked":
            result.blocked.append(label)
        else:
            approved = o.approved or {"edition": None, "deadlines": []}
            if approved["edition"] or approved["deadlines"]:
                path = OFFICIAL_DIR / f"{o.key}.yaml"
                write_official(path, merge_official_doc(load_doc(path), o.key, o.year, approved, today))
                for d in approved["deadlines"]:
                    result.applied.append({**label, "type": d["type"], "label": d["label"],
                                           "date": d["date"], "url": d["evidence"]["url"]})
                if approved["edition"]:
                    e = approved["edition"]
                    result.applied.append({**label, "type": "edition", "label": f"{e['date_text']} @ {e['place']}",
                                           "date": e["start"], "url": e["evidence"]["url"]})
            result.rejected += [{**label, "item": r, "reason": r["reject_reason"]} for r in o.rejected]
            result.held += [{**label, **h} for h in o.held]
            if o.tba:
                result.tba.append({**label, "items": o.tba})
        record(log, o.key, o.year, today, t["criteria"], results_for(t, o), o.access, o.tba, t["urgent"])
    save_checklog(CHECKLOG_PATH, log)

    ok = _rebuild_and_test(run, result)
    after = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    result.upcoming = upcoming_deadlines(after, today)
    if ok:
        result.changes = diff_conferences(before, after)
        if push:
            _commit_and_push(run, result, today)
    else:
        run(["git", "stash", "push", "-u", "-m", f"official-check 실패 {today.isoformat()}"])
        result.failures.append(f"작업 내용은 git stash에 보관 (official-check 실패 {today.isoformat()})")

    report_path = write_report(result)
    if notify and should_send(result):
        summary, truncated = render_summary(result)
        if not send(summary, report_path, truncated):
            result.failures.append("디스코드 전송 실패")
    return 1 if result.failures else 0


def prep_run(today: date, run=_run, fetch=http_fetch) -> int:
    if run(["git", "pull", "--rebase", "--autostash", "origin", "master"]).returncode != 0:
        print("git pull 실패 - 이번 주 확인을 건너뜁니다.")
        return 1
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    targets = select_targets(data, load_checklog(CHECKLOG_PATH), today)
    # 지난 실행의 추출 JSON이 남아 있으면 이번 주 결과로 오인된다. 비우고 시작한다.
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for old in RAW_DIR.iterdir():
        if old.is_file():
            old.unlink()
    WORKLIST_PATH.write_text(json.dumps(targets, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"이번 주 대상 {len(targets)}개 ({today.isoformat()})")
    for t in targets:
        r = fetch_target(t, fetch)
        write_result(r, RAW_DIR)
        tail = ("대체 주소 필요" if r.access == "needs_alternate"
                else f"페이지 {len(r.pages)}개 → data/official/raw/{t['key']}-{t['year']}.txt")
        print(f"- {t['key']} {t['year']} ({t['name']}) 기준 {','.join(t['criteria'])} "
              f"access={r.access} {tail}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prep", "apply"])
    parser.add_argument("--today")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--no-send", action="store_true")
    args = parser.parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()
    if args.command == "prep":
        return prep_run(today)
    return apply_run(today, push=not args.no_push, notify=not args.no_send)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 구현 — Hermes 지시문과 사전 스크립트**

`docs/hermes/official-check.md`:

````markdown
# ConferenceTracker 공식 사이트 확인 (Hermes 지시문)

작업 디렉터리는 저장소 루트다. Python은 반드시 `.venv/bin/python`을 쓴다.
설계: `docs/superpowers/specs/2026-10-07-hermes-official-check-design.md`

## 하는 일

1. 위 사전 스크립트 출력(그리고 `data/official/raw/worklist.json`)이 이번 주 대상이다.
2. `access=needs_alternate`인 대상: 그 학회의 **그 연도 공식 사이트** 주소를 찾는다
   (예: `www.siggraph.org` 대신 `s2027.siggraph.org`). 웹 검색은 주소를 찾는 데만 쓴다.
   찾으면 직접 읽지 말고 이렇게 받게 한다:
   `.venv/bin/python -m scripts.fetch_pages --target <key> <year> --urls <주소1> [<주소2> ...]`
   못 찾으면 건너뛴다.
3. 나머지 대상마다 `data/official/raw/<key>-<year>.txt`**만** 읽고
   `data/official/raw/<key>-<year>.json`을 아래 형식으로 쓴다.
4. 마지막에 `.venv/bin/python -m scripts.official_run apply`를 실행한다.
5. 최종 응답은 한 줄: `apply 종료 코드 <n>`. 결과를 요약하지 않는다 - 보고서는 스크립트가 보낸다.

## 추출 JSON 형식

```json
{"abbr": "<key>", "year": 2027,
 "edition": {"date_text": "August 17-22, 2027", "start": "2027-08-17", "end": "2027-08-22",
             "place": "Kyoto, Japan", "raw_text": "<개최일과 장소가 함께 든 원문 문장>",
             "url": "<그 문장이 있는 섹션 주소>", "confidence": "high"},
 "items": [{"type": "paper", "label": "<페이지의 표현 그대로>", "date": "2027-01-04 23:59:59",
            "timezone": "AoE", "confidence": "high", "raw_text": "<원문 문장 그대로>", "url": "<섹션 주소>"}],
 "not_published": ["<TBA·미공개로 적힌 항목>"],
 "no_track": ["<이 학회에 아예 없는 트랙: poster | lbw | workshop>"]}
```

## 규칙

- `type`은 다음 중 하나만: `paper`(본 논문), `short_paper`, `abstract`, `commitment`(ARR commitment),
  `poster`, `lbw`(late-breaking work), `notification`(어떤 워크숍이 채택됐는지 공개되는 날,
  또는 워크숍 논문 저자 통보일).
- 싣지 않는 것: 워크숍 **제안** 마감(organizer가 내는 것), 튜토리얼, 데모, 박사과정 컨소시엄,
  카메라레디, 등록 마감, 리뷰어·심사위원 관련 날짜.
- `raw_text`는 `.txt`에서 그대로 복사한다. 고치거나 요약하지 않는다. `url`은 그 문장이 든
  `===== <url> =====` 섹션의 주소다. `.txt`에 없는 주소를 쓰지 않는다.
- 날짜를 추측하지 않는다. "approximately", "TBA" 같은 값은 `items`에 넣지 말고 `not_published`에 적는다.
- `timezone`은 그 페이지가 AoE / Anywhere on Earth / UTC-12를 밝힌 경우에만 `"AoE"`. 아니면 넣지 않는다.
- `edition`은 페이지가 개최일과 장소를 함께 밝힌 경우에만. 아니면 `null`.
- 확실하지 않으면 `confidence`를 `medium`이나 `low`로 둔다. 회차·본 논문은 `high`만 반영된다.
- 마감 모음 사이트(ccfddl, ai-deadlines, wikicfp 등)의 값은 근거로 쓰지 않는다.
````

`scripts/hermes_prep.sh`:

```bash
#!/bin/bash
# Hermes cron 사전 스크립트. 출력이 그대로 Hermes 지시문에 들어간다.
set -euo pipefail
cd /Users/jay/Agents/ConferenceManager
exec .venv/bin/python -m scripts.official_run prep
```

```bash
chmod +x scripts/hermes_prep.sh
```

- [ ] **Step 6: 통과와 판별 확인**

Run: `.venv/bin/python -m pytest -q`
Expected: 전체 통과.

판별 확인: `_commit_and_push`의 충돌 분기에서 `reset --hard` 대신 `git checkout --theirs docs/data/conferences.json`을 쓰게 바꾸면 `test_push_conflict_rebuilds_instead_of_merging`이 실패해야 한다. `apply_run`의 `if ok:` 앞 `_rebuild_and_test` 결과를 무시하고 항상 push하게 바꾸면 `test_failed_tests_block_push_and_stash`가 실패해야 한다. `prep_run`의 raw 디렉터리 비우기는 다음 단계에서 실제로 확인한다. 원복.

- [ ] **Step 7: 실제 prep 한 번 (push 없음)**

```bash
.venv/bin/python -m scripts.official_run prep --today 2026-10-12
ls data/official/raw/ | head
git status --short
```
Expected: 대상 목록이 출력되고 `data/official/raw/`에 파일이 생긴다. `git status`에 `data/official/raw/`가 보이지 않는다(gitignore). `git pull`로 원격 변경이 있었다면 그것도 반영된다.

- [ ] **Step 8: 커밋**

```bash
git add scripts/official_run.py scripts/hermes_prep.sh docs/hermes/official-check.md tests/test_official_run.py tests/fixtures/official/acl-2027.extraction.json tests/fixtures/official/chi-2027.extraction.json
git commit -m "공식 사이트 주간 확인 오케스트레이션과 Hermes 지시문

prep은 대상 선정과 수집, apply는 검증·검토·기록·빌드·테스트·push·알림.
Hermes는 둘 사이에서 추출 JSON만 쓴다. 테스트가 실패하면 push하지 않고
작업을 stash에 보관한다. push 충돌은 손 병합 없이 원격 위에서 다시 빌드한다.
prep은 지난 실행의 추출 JSON을 지우고 시작한다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
```

---

### Task 12: 검토자 역검증과 기존 오류 정리

설계 §7a "도입 전 시험". 실제 Claude를 부른다. 기대값과 하나라도 어긋나면 **Task 13으로 넘어가지 않는다.**

**Files:**
- Create: `scripts/backtest_review.py`, `tests/fixtures/official/backtest_cases.json`
- Modify: `data/scraped/raw/ismar.json`, `data/scraped/raw/mm.json`, `data/scraped/raw/uist.json`, `data/scraped/raw/wacv.json` (보류로 확인된 항목 제거)
- Modify: `docs/superpowers/IMPLEMENTATION-PROGRESS.md` (결과 기록)

**Interfaces:**
- Consumes: Task 9의 `review`, `WHAT_FOR_TYPE`; Task 2의 `load_pages`
- Produces: 없음 (판정 기록)

- [ ] **Step 1: 역검증 사례 작성**

`tests/fixtures/official/backtest_cases.json` — 설계 §7a 표 그대로. `pages`는 저장소 안의 파일, `url`은 그 파일 안 섹션 주소(섹션이 없는 옛 파일이면 파일 전체가 그 주소의 본문으로 쓰인다):

```json
[
 {"case": "ACL 2027 paper", "pages": "tests/fixtures/official/acl-2027.txt", "conference": "ACL", "year": 2027,
  "claim": {"type": "paper", "date": "2027-01-04", "raw_text": "<Task 11 Step 1의 ACL 문장>", "url": "<그 섹션 주소>"}, "expect": "pass"},
 {"case": "CHI 2027 paper", "pages": "tests/fixtures/official/chi-2027.txt", "conference": "CHI", "year": 2027,
  "claim": {"type": "paper", "date": "2026-09-10", "raw_text": "<chi-2027.txt의 'Paper submission deadline' 문장>", "url": "https://chi2027.acm.org/authors/papers/"}, "expect": "pass"},
 {"case": "CHI 2027 poster", "pages": "data/scraped/raw/chi.txt", "conference": "CHI", "year": 2027,
  "claim": {"type": "poster", "date": "2027-01-21", "raw_text": "Thursday, January 21, 2027 : Submission deadline", "url": "https://chi2027.acm.org/authors/posters/"}, "expect": "pass"},
 {"case": "CHI 2027 workshop list", "pages": "data/scraped/raw/chi.txt", "conference": "CHI", "year": 2027,
  "claim": {"type": "notification", "date": "2026-12-17", "raw_text": "Thursday, December 17, 2026 : List of accepted workshops released by workshop chairs on the CHI website", "url": "https://chi2027.acm.org/authors/workshops/"}, "expect": "pass"},
 {"case": "ISMAR 2026 poster", "pages": "data/scraped/raw/ismar.txt", "conference": "ISMAR", "year": 2026,
  "claim": {"type": "poster", "date": "2026-06-30", "raw_text": "June 30, 2026: Poster paper submission and optional material submission", "url": "<ismar.yaml의 poster evidence url>"}, "expect": "pass"},
 {"case": "UIST 2026 poster", "pages": "data/scraped/raw/uist.txt", "conference": "UIST", "year": 2026,
  "claim": {"type": "poster", "date": "2026-07-10", "raw_text": "Submission deadline Friday, July 10, 2026", "url": "https://uist.acm.org/2026/cfp#posters"}, "expect": "pass"},
 {"case": "WACV 2027 workshop acceptance", "pages": "data/scraped/raw/wacv.txt", "conference": "WACV", "year": 2027,
  "claim": {"type": "notification", "date": "2026-08-15", "raw_text": "Workshop acceptance notification: August 15, 2026", "url": "https://wacv.thecvf.com/Conferences/2027/CallForWorkshops"}, "expect": "pass"},
 {"case": "WACV 2027 workshop author notification", "pages": "data/scraped/raw/wacv.txt", "conference": "WACV", "year": 2027,
  "claim": {"type": "notification", "date": "2026-10-30", "raw_text": "Author notification deadline (for archival papers): October 30, 2026", "url": "https://wacv.thecvf.com/Conferences/2027/CallForWorkshops"}, "expect": "pass"},
 {"case": "CHI 2027 organizer deadline as notification", "pages": "data/scraped/raw/chi.txt", "conference": "CHI", "year": 2027,
  "claim": {"type": "notification", "date": "2026-10-01", "raw_text": "Thursday, October 1, 2026 : Organizer submission deadline", "url": "https://chi2027.acm.org/authors/workshops/"}, "expect": "hold"},
 {"case": "CHI 2027 approximate participant deadline", "pages": "tests/fixtures/official/chi-2027.txt", "conference": "CHI", "year": 2027,
  "claim": {"type": "workshop", "date": "2027-02-11", "raw_text": "<chi-2027.txt의 'Participant submissions are due approximately' 문장>", "url": "https://chi2027.acm.org/authors/workshops/"}, "expect": "hold"},
 {"case": "ISMAR 2026 workshop proposal", "pages": "data/scraped/raw/ismar.txt", "conference": "ISMAR", "year": 2026,
  "claim": {"type": "workshop", "date": "2026-05-22", "raw_text": "Workshop proposal deadline: May 22nd, 2026 (23:59 AoE, Friday)", "url": "https://www.ieeeismar.net/2026/call-for-workshops/"}, "expect": "hold"},
 {"case": "ACM MM 2026 workshop proposal", "pages": "data/scraped/raw/mm.txt", "conference": "ACM MM", "year": 2026,
  "claim": {"type": "workshop", "date": "2026-02-12", "raw_text": "12th February 2026 - Deadline for submission of workshop proposals.", "url": "https://2026.acmmm.org/site/call-workshops.html"}, "expect": "hold"},
 {"case": "UIST 2026 workshop (organizers)", "pages": "data/scraped/raw/uist.txt", "conference": "UIST", "year": 2026,
  "claim": {"type": "workshop", "date": "2026-07-10", "raw_text": "Submission deadline July 10th, 2026", "url": "https://uist.acm.org/2026/cfp#workshops"}, "expect": "hold"},
 {"case": "WACV 2027 websites live", "pages": "data/scraped/raw/wacv.txt", "conference": "WACV", "year": 2027,
  "claim": {"type": "notification", "date": "2026-08-25", "raw_text": "Workshop websites live by: August 25, 2026", "url": "https://wacv.thecvf.com/Conferences/2027/CallForWorkshops"}, "expect": "hold"}
]
```
`<...>` 자리는 해당 파일을 grep해 실제 문장·주소로 채운다. UIST 7/10 워크숍의 기대값 "hold"의 근거: 같은 페이지에서 바로 뒤에 "Acceptance notification, at which point workshop organizers can begin advertising"이 이어진다 - 제안 마감이다 (2026-10-07 확인).

- [ ] **Step 2: 역검증 스크립트 작성**

`scripts/backtest_review.py`:

```python
"""검토자 역검증 (설계 §7a). 실제 Claude를 부른다 - 단위 테스트가 아니다."""

import json
import sys
from pathlib import Path

import argparse

from scripts.review_official import REVIEW_MODEL, ask_claude, review
from scripts.validate_official import load_pages

ROOT = Path(__file__).parents[1]
CASES = ROOT / "tests" / "fixtures" / "official" / "backtest_cases.json"


def pages_for(path: Path, url: str) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    pages = load_pages(text)
    # 섹션 머리줄이 없는 옛 scraped 파일은 파일 전체를 그 주소의 본문으로 본다.
    return pages if url in pages else {url: text}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=REVIEW_MODEL)
    args = parser.parse_args()
    ask = lambda prompt: ask_claude(prompt, model=args.model)
    print(f"검토 모델: {args.model}")
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    mismatches = 0
    for case in cases:
        claim = case["claim"]
        pages = pages_for(ROOT / case["pages"], claim["url"])
        item = {"type": claim["type"], "label": "-", "date": f"{claim['date']} 23:59:59",
                "evidence": {"raw_text": claim["raw_text"], "url": claim["url"]}}
        approved, held = review({"edition": None, "deadlines": [item]}, pages,
                                case["conference"], case["year"], None, ask=ask)
        got = "pass" if approved["deadlines"] else "hold"
        ok = got == case["expect"]
        mismatches += not ok
        detail = "" if not held else f"  {held[0]['reasons']}  {held[0]['review']}"
        print(f"{'OK ' if ok else 'BAD'} {case['case']:45} 기대 {case['expect']:4} 결과 {got:4}{detail}")
    print(f"\n{len(cases) - mismatches}/{len(cases)} 일치")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: 역검증 실행 - 가벼운 모델부터**

Pro 플랜에서도 매주 부담이 없도록, 14/14를 맞히는 **가장 가벼운** 모델을 검토자로 쓴다.

```bash
.venv/bin/python -m scripts.backtest_review --model claude-haiku-4-5-20251001
.venv/bin/python -m scripts.backtest_review --model claude-sonnet-5
.venv/bin/python -m scripts.backtest_review --model claude-opus-5-5
```
가벼운 순서로 돌리다 `14/14 일치`가 나오면 거기서 멈추고, 그 모델을 `scripts/review_official.py`의 `REVIEW_MODEL`에 넣는다(이미 그 값이면 그대로). 각 모델의 결과(일치 수, 틀린 사례)를 모두 기록한다. 세 모델 모두 14/14가 안 되면 아래 절차로 간다.

어긋나면: 해당 사례의 검토자 답(출력의 `review`)을 읽고 원인을 가린다. (a) 프롬프트의 범주 정의가 모호하면 `DEADLINE_PROMPT`를 고치고 Task 9 테스트를 다시 돌린 뒤 역검증을 처음부터 다시 한다. (b) 기대값 자체가 틀렸다고 판단되면 **고치지 말고 멈춰서** 소유자에게 사례와 원문을 보여 주고 판단을 받는다. 같은 사례에 대해 결과가 실행마다 달라지면 세 번 돌려 다수결을 기록하고 그 사실도 소유자에게 알린다.

- [ ] **Step 4: 결과 기록**

`docs/superpowers/IMPLEMENTATION-PROGRESS.md`에 절을 추가한다: 날짜, 14개 사례별 기대·결과·검토자 답 요약, 프롬프트를 고쳤다면 무엇을 왜.

- [ ] **Step 5: 기존 오류 정리**

역검증에서 "hold"로 확인된 기존 실린 항목 넷을 원본 추출 파일에서 뺀다 - CHI 10/1과 같은 종류의 오류다.

```bash
.venv/bin/python - <<'EOF'
import json, pathlib
drop = {
    "ismar": [("workshop", "2026-05-22")],
    "mm":    [("workshop", "2026-02-12")],
    "uist":  [("workshop", "2026-07-10")],
    "wacv":  [("notification", "2026-08-25")],
}
for abbr, pairs in drop.items():
    p = pathlib.Path(f"data/scraped/raw/{abbr}.json")
    d = json.loads(p.read_text(encoding="utf-8"))
    for e in d["editions"]:
        before = len(e["items"])
        e["items"] = [i for i in e["items"] if (i["type"], i["date"][:10]) not in pairs]
        print(abbr, before, "->", len(e["items"]))
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
EOF
.venv/bin/python -m scripts.validate_scraped
ls data/scraped/
```
`mm`은 남는 항목이 없어 검증기가 `mm.yaml`을 새로 쓰지 않는다(빈 결과로 기존 파일을 지우지 않는 것이 검증기의 규칙이다). 그러니 직접 지운다:

```bash
git rm data/scraped/mm.yaml
.venv/bin/python -m scripts.build && .venv/bin/python scripts/stamp_assets.py
.venv/bin/python -m pytest -q && node --test tests/js/
grep -c '"Workshops"' docs/data/conferences.json
```
Expected: 테스트 통과. `conferences.json`에서 ISMAR·MM·UIST의 `Workshops` 항목과 WACV `Workshop websites live by`가 사라진다. `tests/test_source_scraped.py`나 `tests/test_registry_completeness.py`가 MM scraped 파일을 전제하고 있으면 실패할 수 있다 - 그 경우 전제가 바뀐 것이니 테스트의 기대값을 고치고 커밋 메시지에 적는다.

- [ ] **Step 6: 커밋**

```bash
git add scripts/backtest_review.py tests/fixtures/official/backtest_cases.json data/scraped docs/data/conferences.json docs/index.html docs/app.js docs/superpowers/IMPLEMENTATION-PROGRESS.md
git commit -m "검토자 역검증 14/14, 기존 워크숍 제안 마감 정리

정답을 아는 14개 사례로 Claude 검토자를 시험했다. 통과해야 할 8개는
통과, 보류해야 할 6개는 보류. 결과는 IMPLEMENTATION-PROGRESS에 기록.

역검증으로 확인된 기존 오류 넷을 뺐다: ISMAR·ACM MM·UIST 2026의 워크숍
제안 마감, WACV 2027의 'Workshop websites live by'. CHI 10/1과 같은
종류로, 문장도 날짜도 실재해서 게이트를 통과했던 값이다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
git push origin master
```

---

### Task 13: Hermes cron 등록과 첫 실행

설계 §12. 이 태스크는 저장소 밖(Hermes 설정)을 바꾸고 실제로 push와 디스코드 전송을 한다. **Task 12가 14/14로 끝난 뒤에만** 시작한다.

**Files:**
- Modify: Hermes `research` 프로필의 스크립트 디렉터리, cron 작업 (저장소 밖)
- Modify: `docs/superpowers/IMPLEMENTATION-PROGRESS.md`

**Interfaces:**
- Consumes: Task 11의 `scripts/hermes_prep.sh`, `docs/hermes/official-check.md`, `scripts.official_run`

- [ ] **Step 1: 사전 스크립트 위치와 cron 시간대 확인**

```bash
research cron create --help | grep -A3 -- "--script"
ls ~/.hermes/profiles/research/ | grep -i script || echo "scripts 디렉터리 없음"
```
`--script`가 찾는 디렉터리가 `~/.hermes/scripts/`인지 `~/.hermes/profiles/research/scripts/`인지 확인하고, 그 디렉터리에 연결한다:

```bash
SCRIPTS_DIR=~/.hermes/profiles/research/scripts   # 위 확인 결과로 바꾼다
mkdir -p "$SCRIPTS_DIR"
ln -sf /Users/jay/Agents/ConferenceManager/scripts/hermes_prep.sh "$SCRIPTS_DIR/conftracker-prep.sh"
```

시간대 확인 (일시 정지 상태로 만들어 다음 실행 시각만 본다):

```bash
research cron create "0 10 * * 1" "probe" --name tz-probe --paused
research cron list
research cron remove tz-probe
```
Expected: `tz-probe`의 다음 실행이 다가오는 월요일 10:00 **KST**. UTC로 해석된다면 등록 시 `"0 1 * * 1"`을 쓴다. 결과를 기록한다.

- [ ] **Step 2: cron 환경에서 claude와 research가 도는지 확인**

```bash
cat > "$SCRIPTS_DIR/conftracker-probe.sh" <<'EOF'
#!/bin/bash
echo "PATH=$PATH"
echo '{"ok": 1}만 답하라' | ~/.local/bin/claude -p --tools "" --output-format json --no-session-persistence | head -c 300
echo
~/.local/bin/research send --list | head -3
EOF
chmod +x "$SCRIPTS_DIR/conftracker-probe.sh"
research cron create "every 1m" --name conftracker-probe --script conftracker-probe.sh --no-agent --deliver local --repeat 1
```
1–2분 뒤:

```bash
research cron runs conftracker-probe
research cron remove conftracker-probe
rm "$SCRIPTS_DIR/conftracker-probe.sh"
```
Expected: claude 출력에 `"is_error":false`, research가 Discord 대상을 보여준다. claude가 로그인 오류를 내면 cron 환경에 Claude 인증이 없는 것이다 - 멈추고 소유자에게 알린다 (설계 §11: 검토 없이 반영하는 경로는 없으므로 이 상태로는 아무것도 반영되지 않는다).

- [ ] **Step 3: 손으로 한 번 끝까지 (push·전송 없이)**

```bash
cd /Users/jay/Agents/ConferenceManager
.venv/bin/python -m scripts.official_run prep > /tmp/prep.txt; cat /tmp/prep.txt
research -z "$(cat /tmp/prep.txt; echo; echo '위가 이번 주 대상 목록이다. docs/hermes/official-check.md를 읽고 그대로 따르되, 마지막 단계는 .venv/bin/python -m scripts.official_run apply --no-push --no-send 로 실행하라.')" --in /Users/jay/Agents/ConferenceManager
cat ~/.hermes/reports/conference-tracker/$(date +%F).md
git status --short && git diff --stat
```
Expected: 보고서에 대상 수, 반영·보류·탈락·접속 실패가 있다. `data/official/*.yaml`과 `checklog.yaml`이 생기고 테스트가 통과했다. 반영된 항목마다 보고서의 근거 주소를 열어 날짜가 맞는지 **직접 확인한다.** 하나라도 틀리면 멈추고 원인을 찾는다 (게이트·해석 규칙·검토자 중 어디서 놓쳤는지 기록).

- [ ] **Step 4: 첫 실제 실행 (push·전송 포함)**

Step 3의 변경을 되돌리고 처음부터 실제로 돈다:

```bash
git stash push -u -m "dry run" -- data/official docs
.venv/bin/python -m scripts.official_run prep > /tmp/prep.txt
research -z "$(cat /tmp/prep.txt; echo; echo '위가 이번 주 대상 목록이다. docs/hermes/official-check.md를 읽고 그대로 따르라.')" --in /Users/jay/Agents/ConferenceManager
git log --oneline -3
```
Expected: `공식 사이트 주간 확인 (YYYY-MM-DD)` 커밋이 master에 push되고, 디스코드에 요약이 온다. 소유자에게 디스코드 메시지가 왔는지 확인받는다. dry run stash는 `git stash drop`으로 버린다.

- [ ] **Step 5: cron 등록**

```bash
research cron create "0 10 * * 1" \
  "ConferenceTracker 공식 사이트 주간 확인. 위 사전 스크립트 출력이 이번 주 대상 목록이다. 저장소의 docs/hermes/official-check.md를 읽고 그대로 따르라." \
  --name conference-tracker-official \
  --script conftracker-prep.sh \
  --workdir /Users/jay/Agents/ConferenceManager \
  --deliver local \
  --failure-deliver discord
research cron list
research cron doctor
```
(Step 1에서 cron이 UTC로 해석됐다면 `"0 1 * * 1"`.) `--deliver local`인 이유: 정상 결과는 스크립트가 보고서를 보낸다. Hermes 자체가 실패했을 때만 `--failure-deliver discord`로 알림이 간다.

Expected: `conference-tracker-official`이 active, 다음 실행이 다가오는 월요일 10:00 KST, `doctor`에 경고 없음.

- [ ] **Step 6: 기록과 커밋**

`docs/superpowers/IMPLEMENTATION-PROGRESS.md`에 절을 추가한다: cron 이름과 일정, 스크립트 연결 위치, 시간대 확인 결과, claude/research cron 환경 확인 결과, 첫 실행 결과(대상 수, 반영·보류·탈락, 직접 확인한 항목), 그리고 확인 방법:

```
research cron list                      # 등록 상태
research cron runs conference-tracker-official
ls ~/.hermes/reports/conference-tracker/
```

```bash
git add docs/superpowers/IMPLEMENTATION-PROGRESS.md
git commit -m "공식 사이트 주간 확인 cron 등록 기록

Hermes research 프로필, 매주 월 10:00 KST. 첫 실행 결과와 확인 방법을
남긴다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XGJ5Wnow4Uw5qSoPZzxUjv"
git push origin master
```

- [ ] **Step 7: 다음 월요일 확인 (등록이 아니라 실제 실행)**

GitHub Actions cron 때의 교훈: "설정했다"가 아니라 "돌았다"를 확인한다. 다음 월요일 오후에:

```bash
research cron runs conference-tracker-official
git log --oneline origin/master -5
ls -la ~/.hermes/reports/conference-tracker/
```
Expected: 그 월요일 실행 기록이 있고, 바뀐 것이 있었다면 커밋과 디스코드 메시지가 있다. 실행 기록이 없으면 원인(맥 꺼짐, 게이트웨이 중단, 일정 해석)을 찾아 기록한다.
