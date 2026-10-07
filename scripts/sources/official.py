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
