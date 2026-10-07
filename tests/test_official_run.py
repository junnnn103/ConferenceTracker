import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from scripts import official_run as orun
from scripts.report import RunResult

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
    (raw / "prep.json").write_text(json.dumps({"date": TODAY.isoformat()}), encoding="utf-8")
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
    stash = [c for c in calls if c[:3] == ["git", "stash", "push"]]
    assert stash and "--" in stash[0], "관련 없는 작업은 쓸어 담지 않는다"
    assert stash[0][stash[0].index("--") + 1:] == orun.COMMIT_PATHS
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
        if cmd[:2] == ["git", "rev-parse"]:
            return Proc(0, out="abc123\n")
        if cmd[:2] == ["git", "rebase"] and cmd[2:] == ["origin/master"]:
            return Proc(1, err="CONFLICT docs/data/conferences.json")
        return Proc(0)

    run, calls = wire(monkeypatch, tmp_path, script)
    code = orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run, send=lambda s, p, a: True)
    assert code == 0
    i = calls.index(["git", "rebase", "--abort"])
    after = calls[i:]
    assert after[1:3] == [["git", "rev-parse", "HEAD"], ["git", "reset", "--hard", "origin/master"]]
    assert ["git", "checkout", "abc123", "--", "data/official"] in after
    assert not any(c[:2] == ["git", "stash"] for c in calls), "stash는 쓰지 않는다"
    assert any("scripts.build" in " ".join(c) for c in after), "다시 빌드한다"
    assert not any(c[:2] == ["git", "checkout"] and "--theirs" in c for c in calls), "손 병합 금지"


def test_malformed_extraction_does_not_abort_other_targets(monkeypatch, tmp_path):
    """LLM 출력은 믿지 않는다. 한 대상이 터져도 나머지는 처리한다."""
    run, calls = wire(monkeypatch, tmp_path, lambda cmd: Proc(1 if cmd[:3] == ["git", "diff", "--cached"] else 0))
    raw = tmp_path / "raw"
    shutil.copy(FIX / "chi-2027.txt", raw / "chi-2027.txt")
    (raw / "chi-2027.json").write_text(
        json.dumps({"abbr": "chi", "year": 2027, "edition": None, "items": [123]}), encoding="utf-8")
    (raw / "chi-2027.fetch.json").write_text(json.dumps({"access": "ok"}), encoding="utf-8")
    (raw / "worklist.json").write_text(
        json.dumps([target("chi", ["C"]), target("acl", ["D"])]), encoding="utf-8")
    sent = []
    code = orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run,
                          send=lambda s, p, a: sent.append(s) or True)
    assert code == 1
    assert "CHI 2027: 처리 중 오류" in sent[0]
    assert (tmp_path / "official" / "acl.yaml").exists(), "다른 대상은 계속 처리한다"
    log = (tmp_path / "official" / "checklog.yaml").read_text(encoding="utf-8")
    assert "acl/2027" in log and "chi/2027" not in log, "실패한 대상은 기록하지 않는다"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def test_push_conflict_with_real_git_keeps_our_data_and_unrelated_stash(monkeypatch, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "master", str(remote)], check=True, capture_output=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True)
    for cfg in (("user.name", "t"), ("user.email", "t@example.com")):
        git(clone, "config", *cfg)
    (clone / "docs" / "data").mkdir(parents=True)
    (clone / "data" / "official").mkdir(parents=True)
    (clone / "docs" / "data" / "conferences.json").write_text("base", encoding="utf-8")
    (clone / "docs" / "index.html").write_text("x", encoding="utf-8")
    (clone / "docs" / "app.js").write_text("x", encoding="utf-8")
    (clone / "data" / "official" / ".keep").write_text("", encoding="utf-8")
    (clone / "notes.txt").write_text("v1", encoding="utf-8")
    git(clone, "add", "-A")
    git(clone, "commit", "-m", "base")
    git(clone, "push", "origin", "HEAD:master")
    # 관련 없는 예전 stash
    (clone / "notes.txt").write_text("v2", encoding="utf-8")
    git(clone, "stash", "push", "-m", "unrelated")
    # 원격에서 conferences.json이 바뀐다 (Actions)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
    for cfg in (("user.name", "t"), ("user.email", "t@example.com")):
        git(other, "config", *cfg)
    (other / "docs" / "data" / "conferences.json").write_text("remote", encoding="utf-8")
    git(other, "commit", "-am", "actions")
    git(other, "push", "origin", "HEAD:master")
    # 우리 작업
    (clone / "docs" / "data" / "conferences.json").write_text("local", encoding="utf-8")
    (clone / "data" / "official" / "acl.yaml").write_text("acl: new\n", encoding="utf-8")
    (clone / "data" / "official" / "checklog.yaml").write_text("acl/2027: checked\n", encoding="utf-8")

    monkeypatch.setattr(orun, "BUILD_STEPS", [("빌드", [sys.executable, "-c",
        "open('docs/data/conferences.json','w').write('rebuilt:'+open('data/official/acl.yaml').read())"])])
    real = lambda cmd: subprocess.run(cmd, cwd=clone, capture_output=True, text=True)
    result = RunResult(today=TODAY, targets=[])
    orun._commit_and_push(real, result, TODAY)

    assert result.failures == []
    git(clone, "fetch", "origin")
    assert git(clone, "show", "origin/master:data/official/acl.yaml") == "acl: new\n"
    assert git(clone, "show", "origin/master:data/official/checklog.yaml") == "acl/2027: checked\n"
    assert git(clone, "show", "origin/master:docs/data/conferences.json") == "rebuilt:acl: new\n"
    stashes = git(clone, "stash", "list")
    assert "unrelated" in stashes and len(stashes.strip().splitlines()) == 1
    assert (clone / "notes.txt").read_text(encoding="utf-8") == "v1", "stash를 건드리지 않았다"


def test_prep_clears_raw_before_pull_failure(monkeypatch, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "acl-2027.json").write_text("{}", encoding="utf-8")
    (raw / "prep.json").write_text(json.dumps({"date": TODAY.isoformat()}), encoding="utf-8")
    monkeypatch.setattr(orun, "RAW_DIR", raw)
    assert orun.prep_run(TODAY, run=lambda cmd: Proc(1)) == 1
    assert list(raw.iterdir()) == []


def test_apply_refuses_stale_prep(monkeypatch, tmp_path):
    run, calls = wire(monkeypatch, tmp_path, lambda cmd: Proc(0))
    (tmp_path / "raw" / "prep.json").write_text(json.dumps({"date": "2026-10-05"}), encoding="utf-8")
    sent = []
    code = orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run,
                          send=lambda s, p, a: sent.append(s) or True)
    assert code == 1
    assert "prep 기록이 없거나 오늘 것이 아님" in sent[0]
    assert not (tmp_path / "official" / "acl.yaml").exists()
    assert not (tmp_path / "official" / "checklog.yaml").exists()
    assert calls == [], "빌드도 push도 하지 않는다"


def test_held_only_target_stays_tba_in_checklog(monkeypatch, tmp_path):
    run, calls = wire(monkeypatch, tmp_path, lambda cmd: Proc(1 if cmd[:3] == ["git", "diff", "--cached"] else 0))
    # 미공개 항목이 없는 추출: 보류만이 다음 주 재확인의 이유다.
    path = tmp_path / "raw" / "acl-2027.json"
    ext = json.loads(path.read_text(encoding="utf-8"))
    ext["not_published"] = []
    path.write_text(json.dumps(ext), encoding="utf-8")
    # 검토자가 추출과 다르게 답하면 보류된다.
    disagree = ("ARR submission deadline", {"who_submits": "none", "what": "other", "event_year": 2027,
                                             "exact": True, "date": "2027-01-04"})
    orun.apply_run(TODAY, ask=agree_with([disagree]), run=run, send=lambda s, p, a: True)
    import yaml
    entry = yaml.safe_load((tmp_path / "official" / "checklog.yaml").read_text(encoding="utf-8"))
    entry = entry["acl/2027"]
    assert entry["results"]["D"] == "tba" and entry["tba"]


def test_apply_with_empty_raw_dir_reports_instead_of_crashing(monkeypatch, tmp_path):
    run, calls = wire(monkeypatch, tmp_path, lambda cmd: Proc(0))
    for f in (tmp_path / "raw").iterdir():
        f.unlink()
    sent = []
    code = orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run,
                          send=lambda s, p, a: sent.append(s) or True)
    assert code == 1
    assert "prep 기록이 없거나 오늘 것이 아님" in sent[0]
    assert calls == []


def test_conflict_recovery_failure_stops_before_push(monkeypatch, tmp_path):
    pushes = []

    def script(cmd):
        if cmd[:3] == ["git", "diff", "--cached"]:
            return Proc(1)
        if cmd[:2] == ["git", "push"]:
            pushes.append(cmd)
            return Proc(1)
        if cmd[:2] == ["git", "rebase"] and cmd[2:] == ["origin/master"]:
            return Proc(1)
        if cmd[:2] == ["git", "rev-parse"]:
            return Proc(0, out="abc123\n")
        if cmd[:2] == ["git", "checkout"]:
            return Proc(1, err="pathspec")
        return Proc(0)

    calls = []
    run = lambda cmd: calls.append(cmd) or script(cmd)
    result = RunResult(today=TODAY, targets=[])
    orun._commit_and_push(run, result, TODAY)
    assert len(pushes) == 1, "복구가 실패한 뒤에는 push하지 않는다"
    assert any("push 충돌 복구 실패" in f for f in result.failures)
    assert not any("scripts.build" in " ".join(c) for c in calls)
