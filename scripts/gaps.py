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
