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
        try:
            o = process_target(t, RAW_DIR, before, ask)
        except Exception as exc:  # LLM 출력은 믿지 않는다. 한 대상이 전체 실행을 멈추게 하지 않는다.
            result.failures.append(f"{t['abbr']} {t['year']}: 처리 중 오류: {exc}")
            continue  # 기록을 갱신하지 않으므로 다음 주에 다시 본다
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
