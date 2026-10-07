"""実行 보고서와 디스코드 전송 (설계 §10).

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
    if run.upcoming:
        lines += ["", "[14일 안 마감]"] + [f"- D-{u.get('dday')} {u.get('abbr')} {u.get('label')} ({u.get('date')})"
                                         for u in run.upcoming]
    if run.blocked:
        lines += ["", "[접속 실패]"] + [f"- {b.get('abbr')} {b.get('year')}" for b in run.blocked]
    if run.applied:
        lines += ["", "[반영]"] + [f"- {a.get('abbr')} {a.get('year')} {a.get('label')}: {(a.get('date') or '')[:10]} <{a.get('url')}>"
                                   for a in run.applied]
    if run.held:
        lines += ["", "[보류: 해석 불일치 - 확인 필요]"] + [
            f"- {h.get('abbr')} {h.get('year')} {h.get('item', {}).get('type')} {str(h.get('item', {}).get('date', ''))[:10]}"
            f" {h.get('item', {}).get('label', '')}: {', '.join(h.get('reasons', []))}" for h in run.held]
    if run.rejected:
        lines += ["", "[게이트 탈락]"] + [f"- {r.get('abbr')} {r.get('year')} {r.get('item', {}).get('type')}: {r.get('reason')}"
                                       for r in run.rejected]
    if run.tba:
        lines += ["", "[아직 미공개]"] + [f"- {t.get('abbr')} {t.get('year')}: {'; '.join(t.get('items', []))}" for t in run.tba]
    return lines


def render_summary(run: RunResult) -> tuple[str, bool]:
    text = "\n".join(_lines(run))
    if len(text) <= DISCORD_LIMIT:
        return text, False
    tail = "\n… (전체 보고서 첨부)"
    return text[: DISCORD_LIMIT - 200].rsplit("\n", 1)[0] + tail, True


def render_report(run: RunResult) -> str:
    lines = _lines(run)
    if run.changes:
        lines += ["", "[사이트 값 변경 (이전 → 새 값)]"] + [
            f"- {c.get('abbr')} {c.get('year')} {c.get('field')}: {c.get('old')} → {c.get('new')}" for c in run.changes]
    if run.held:
        lines += ["", "[보류 항목 상세]"]
        for h in run.held:
            lines += [f"- {h.get('abbr')} {h.get('year')}", f"  추출: {h.get('item')}", f"  검토: {h.get('review')}"]
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
    try:
        message = summary + (f"\nMEDIA:{report_path}" if attach else "")
        proc = runner([research_bin(), "send", "-t", "discord", message],
                      capture_output=True, text=True, timeout=60)
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False
