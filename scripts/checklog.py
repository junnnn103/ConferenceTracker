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
