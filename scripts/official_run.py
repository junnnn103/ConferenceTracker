"""공식 사이트 주간 확인의 두 단계 (설계 §5).

prep  : 대상 선정 → 페이지 수집 → Hermes에게 넘길 목록 출력 (cron 사전 스크립트)
apply : 검증 → 독립 검토 → 공식 값 기록 → 빌드·테스트 → 커밋·push → 보고·알림
Hermes는 두 단계 사이에서 추출 JSON을 쓰는 일만 한다.
"""

import argparse
import json
import shutil
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
# cron 환경의 PATH에는 /opt/homebrew/bin이 없을 수 있다.
NODE = shutil.which("node") or "/opt/homebrew/bin/node"

BUILD_STEPS = [
    ("빌드", [PY, "-m", "scripts.build"]),
    ("정적 자원 도장", [PY, "scripts/stamp_assets.py"]),
    ("Python 테스트", [PY, "-m", "pytest", "-q"]),
    ("JS 테스트", [NODE, "--test", "tests/js/"]),
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
    # 실행 파일이 없거나 시간이 넘어도 실패한 명령으로 돌려준다 - 보고서는 반드시 나간다.
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(cmd, 1, "", f"{type(exc).__name__}: {exc}")


def _str_list(value) -> list[str]:
    """Hermes가 쓴 not_published / no_track을 문자열 목록으로 맞춘다.

    목록이 아니면 버리고(문자열 하나를 글자로 쪼개지 않게), 목록 안의 문자열이 아닌
    값도 버린다. LLM 출력은 믿지 않는다.
    """
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]


def changed_only(approved: dict) -> dict:
    """data/official에 쓸 것: 검토를 거친 새 값만. 그대로인 값(unchanged)은 쓰지 않는다."""
    edition = approved.get("edition")
    return {"edition": edition if edition and not edition.get("unchanged") else None,
            "deadlines": [d for d in approved.get("deadlines") or [] if not d.get("unchanged")]}


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
                         _str_list(extraction.get("not_published")),
                         _str_list(extraction.get("no_track")))


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
            # 보류 항목이 있거나 미공개 항목이 있으면 다음 주에 다시 본다.
            done = bool(approved["edition"] or approved["deadlines"])
            out[c] = "found" if done and not o.held and not o.tba else "tba"
        else:
            out[c] = "found"
    return out


def _rebuild_and_test(run, result: RunResult) -> bool:
    for name, cmd in BUILD_STEPS:
        proc = run(cmd)
        if proc.returncode != 0:
            result.failures.append(f"{name} 실패: {_detail(proc)}")
            result.applied = []  # 게시하지 않으므로 "반영"이라고 말하지 않는다
            return False
    return True


def _detail(proc) -> str:
    return (proc.stderr or proc.stdout or "").strip()[-300:]


def _commit(run, result: RunResult, message: str) -> bool:
    """커밋을 만들었으면 True. 바뀐 것이 없거나 커밋이 실패하면 False (실패는 기록한다)."""
    run(["git", "add", *COMMIT_PATHS])
    if run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return False
    proc = run(["git", *BOT, "commit", "-m", message])
    if proc.returncode != 0:
        result.failures.append(f"git commit 실패: {_detail(proc)}")
        result.applied = []  # 게시되지 않았다
        return False
    return True


def _commit_and_push(run, result: RunResult, today: date) -> None:
    message = (f"공식 사이트 주간 확인 ({today.isoformat()})\n\n"
               f"반영 {len(result.applied)}건, 보류 {len(result.held)}건, "
               f"탈락 {len(result.rejected)}건, 접속 실패 {len(result.blocked)}건.")
    if not _commit(run, result, message):
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
        head = run(["git", "rev-parse", "HEAD"])
        sha = (head.stdout or "").strip()
        if head.returncode != 0 or not sha:
            result.failures.append("push 충돌 복구 실패: git rev-parse HEAD")
            return
        if run(["git", "reset", "--hard", "origin/master"]).returncode != 0:
            result.failures.append(f"push 충돌 복구 실패: git reset --hard origin/master (우리 커밋 {sha[:10]})")
            return
        if run(["git", "checkout", sha, "--", "data/official"]).returncode != 0:
            result.failures.append(f"push 충돌 복구 실패: git checkout {sha[:10]} -- data/official")
            return
        if not _rebuild_and_test(run, result):
            result.failures.append(f"push 충돌 후 재빌드 실패 (우리 커밋 {sha[:10]})")
            return
        failures = len(result.failures)
        if not _commit(run, result, message) and len(result.failures) > failures:
            return
    result.failures.append("push 실패 (3회 시도)")


def _prep_is_today(today: date) -> bool:
    try:
        meta = json.loads((RAW_DIR / "prep.json").read_text(encoding="utf-8"))
        return meta.get("date") == today.isoformat()
    except (OSError, ValueError, AttributeError):
        return False


def _fallback_summary(result: RunResult, exc: Exception) -> str:
    lines = [f"📅 ConferenceTracker 공식 사이트 확인 ({result.today.isoformat()})",
             f"대상 {len(result.targets)} · 반영 {len(result.applied)} · 보류 {len(result.held)} · "
             f"탈락 {len(result.rejected)} · 접속 실패 {len(result.blocked)}",
             f"보고서 생성 실패: {type(exc).__name__}: {exc}"[:300]]
    lines += [f"- {str(f)[:200]}" for f in result.failures]
    return "\n".join(lines)[:1900]


def _finish(result: RunResult, send, notify: bool) -> int:
    try:
        report_path = write_report(result)
        summary, truncated = render_summary(result)
        wanted = should_send(result)
    except Exception as exc:  # 커밋·push 뒤일 수 있다. 알림은 반드시 보낸다.
        summary, truncated, wanted = _fallback_summary(result, exc), False, True
        report_path = Path()
        result.failures.append(f"보고서 생성 실패: {exc}")
    if notify and wanted:
        if not send(summary, report_path, truncated):
            result.failures.append("디스코드 전송 실패")
    return 1 if result.failures else 0


def _branch_problem(run) -> str | None:
    proc = run(["git", "branch", "--show-current"])
    branch = (proc.stdout or "").strip()
    if proc.returncode != 0 or branch != "master":
        return f"master 브랜치가 아님 ({branch or _detail(proc) or '알 수 없음'})"
    return None


def apply_run(today: date, ask=ask_claude, run=_run, send=send_discord,
              push: bool = True, notify: bool = True) -> int:
    before = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    problem = _branch_problem(run)
    if problem:
        result = RunResult(today=today, targets=[])
        result.failures.append(f"{problem} - 반영하지 않음")
        result.upcoming = upcoming_deadlines(before, today)
        return _finish(result, send, notify)
    worklist = None
    if _prep_is_today(today):
        try:
            worklist = json.loads(WORKLIST_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            worklist = None
    if worklist is None:
        result = RunResult(today=today, targets=[])
        result.failures.append("prep 기록이 없거나 오늘 것이 아님 - 반영하지 않음")
        result.upcoming = upcoming_deadlines(before, today)
        return _finish(result, send, notify)
    # 스크립트만 data/official을 고친다. 그 밖의 변경(Hermes가 지시를 어긴 경우 등)이
    # 있으면 검증·검토 없이 커밋될 수 있으므로 아무것도 반영하지 않는다. raw/는 git 무시.
    status = run(["git", "status", "--porcelain", "--", "data/official"])
    dirty = [line[3:] for line in (status.stdout or "").splitlines() if line.strip()]
    if status.returncode != 0 or dirty:
        result = RunResult(today=today, targets=worklist)
        files = ", ".join(dirty) if dirty else f"git status 실패: {_detail(status)}"
        result.failures.append(f"data/official에 스크립트 밖의 변경이 있어 반영하지 않음: {files}")
        result.upcoming = upcoming_deadlines(before, today)
        return _finish(result, send, notify)
    log = load_checklog(CHECKLOG_PATH)
    result = RunResult(today=today, targets=worklist)

    for t in worklist:
        label = {"abbr": t["abbr"], "year": t["year"]}
        try:
            o = process_target(t, RAW_DIR, before, ask)
            if o.error:
                result.failures.append(f"{t['abbr']} {t['year']}: {o.error}")
                continue  # 기록을 갱신하지 않으므로 다음 주에 다시 본다
            if o.access == "blocked":
                result.blocked.append(label)
            else:
                # 그대로인 값은 쓰지 않는다 (results_for에서는 찾은 것으로 센다).
                approved = changed_only(o.approved or {"edition": None, "deadlines": []})
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
        except Exception as exc:  # LLM 출력은 믿지 않는다. 한 대상이 전체 실행을 멈추게 하지 않는다.
            result.failures.append(f"{t['abbr']} {t['year']}: 처리 중 오류: {exc}")
            continue  # 기록을 갱신하지 않으므로 다음 주에 다시 본다
        # 보류 항목도 다음 주에 다시 보도록 tba에 남긴다.
        held_labels = [(h.get("item") or {}).get("label") or (h.get("item") or {}).get("type") or "?"
                       for h in o.held]
        record(log, o.key, o.year, today, t["criteria"], results_for(t, o), o.access,
               list(o.tba) + held_labels, t["urgent"])
    save_checklog(CHECKLOG_PATH, log)

    ok = _rebuild_and_test(run, result)
    try:
        after = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # 빌드가 중간에 실패했을 수 있다
        after = before
    result.upcoming = upcoming_deadlines(after, today)
    if ok:
        result.changes = diff_conferences(before, after)
        if push:
            _commit_and_push(run, result, today)
    else:
        stash = run(["git", "stash", "push", "-u", "-m", f"official-check 실패 {today.isoformat()}", "--", *COMMIT_PATHS])
        if stash.returncode != 0:
            result.failures.append(f"git stash 실패: {_detail(stash)} - 작업 내용이 작업 트리에 남아 있음")
        else:
            result.failures.append(f"작업 내용은 git stash에 보관 (official-check 실패 {today.isoformat()})")
    return _finish(result, send, notify)


def _prep_failed(today: date, send, reason: str) -> int:
    # 이 줄을 Hermes가 읽고 멈춘다 (docs/hermes/official-check.md).
    message = f"준비 실패: {reason} - 이번 주 확인을 건너뜁니다."
    print(message)
    send(f"📅 ConferenceTracker 공식 사이트 확인 ({today.isoformat()})\n{message}", Path(), False)
    return 1


def prep_run(today: date, run=_run, fetch=http_fetch, send=send_discord) -> int:
    # 지난 실행의 추출 JSON이 남아 있으면 이번 주 결과로 오인된다. 무엇보다 먼저 비운다.
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for old in RAW_DIR.iterdir():
        if old.is_file():
            old.unlink()
    problem = _branch_problem(run)
    if problem:
        return _prep_failed(today, send, problem)
    pull = run(["git", "pull", "--rebase", "--autostash", "origin", "master"])
    if pull.returncode != 0:
        # 리베이스 도중에 멈춘 채로 두면 다음 주도 실패한다.
        run(["git", "rebase", "--abort"])
        return _prep_failed(today, send, f"git pull 실패 ({_detail(pull)[-150:]})")
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    targets = select_targets(data, load_checklog(CHECKLOG_PATH), today)
    WORKLIST_PATH.write_text(json.dumps(targets, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"이번 주 대상 {len(targets)}개 ({today.isoformat()})")
    for t in targets:
        r = fetch_target(t, fetch)
        write_result(r, RAW_DIR)
        tail = ("대체 주소 필요" if r.access == "needs_alternate"
                else f"페이지 {len(r.pages)}개 → data/official/raw/{t['key']}-{t['year']}.txt")
        print(f"- {t['key']} {t['year']} ({t['name']}) 기준 {','.join(t['criteria'])} "
              f"access={r.access} {tail}")
    # 끝까지 수집했을 때만 오늘 것으로 표시한다.
    (RAW_DIR / "prep.json").write_text(json.dumps({"date": today.isoformat()}), encoding="utf-8")
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
