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


BRANCH = ["git", "branch", "--show-current"]
STATUS = ["git", "status", "--porcelain", "--", "data/official"]


def wire(monkeypatch, tmp_path, script, branch="master", dirty=""):
    """apply_run이 쓰는 경로를 tmp로 돌리고, 명령 실행을 script(cmd)->Proc로 바꾼다.

    브랜치 확인과 data/official 상태 확인은 branch/dirty로 답한다."""
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
        if cmd == BRANCH:
            return Proc(0, out=branch + "\n")
        if cmd == STATUS:
            return Proc(0, out=dirty)
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
    fetch = isolate_prep(monkeypatch, tmp_path)
    assert orun.prep_run(TODAY, run=lambda cmd: Proc(1), fetch=fetch, send=lambda s, p, a: True) == 1
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
    assert calls == [BRANCH], "빌드도 push도 하지 않는다"


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
    assert calls == [BRANCH]


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


# ---- 최종 검토 반영 ----

def ok_script(cmd):
    return Proc(1 if cmd[:3] == ["git", "diff", "--cached"] else 0)


def capture():
    sent = []
    return sent, (lambda s, p, a: sent.append(s) or True)


def test_I1_missing_build_binary_is_reported_not_raised(monkeypatch, tmp_path):
    """node가 cron PATH에 없거나 시간 초과여도 보고서를 보낸다."""
    def script(cmd):
        if cmd[0] == "git":
            return ok_script(cmd)
        return orun._run(cmd)  # 실제 _run

    run, calls = wire(monkeypatch, tmp_path, script)
    monkeypatch.setattr(orun, "BUILD_STEPS", [("JS 테스트", ["/nonexistent/definitely-not-node", "--test"])])
    sent, send = capture()
    code = orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run, send=send)
    assert code == 1
    assert "JS 테스트 실패" in sent[0] and "FileNotFoundError" in sent[0]
    assert not any(c[:2] == ["git", "push"] for c in calls)


def test_I1_run_converts_timeout_to_failed_process(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 900)
    monkeypatch.setattr(orun.subprocess, "run", boom)
    proc = orun._run(["node", "--test"])
    assert proc.returncode == 1 and "TimeoutExpired" in proc.stderr


def test_I1_node_is_resolved_outside_path():
    node = [cmd for name, cmd in orun.BUILD_STEPS if name == "JS 테스트"][0][0]
    assert node.endswith("node") and node.startswith("/")


def test_I2_malformed_not_published_and_no_track_are_coerced(monkeypatch, tmp_path):
    run, calls = wire(monkeypatch, tmp_path, ok_script)
    path = tmp_path / "raw" / "acl-2027.json"
    ext = json.loads(path.read_text(encoding="utf-8"))
    ext["not_published"] = [{"x": 1}, "Commitment deadline"]
    ext["no_track"] = "poster"
    path.write_text(json.dumps(ext), encoding="utf-8")
    o = orun.process_target(target("acl", ["D"]), tmp_path / "raw", {"conferences": []}, agree_with([ACL_PAPER]))
    assert o.tba == ["Commitment deadline"] and o.no_track == []
    sent, send = capture()
    orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run, send=send)
    import yaml
    entry = yaml.safe_load((tmp_path / "official" / "checklog.yaml").read_text(encoding="utf-8"))["acl/2027"]
    assert all(isinstance(x, str) for x in entry["tba"])
    assert sent and "Commitment deadline" in sent[0]


def test_I2_render_failure_still_sends_fallback(monkeypatch, tmp_path):
    run, calls = wire(monkeypatch, tmp_path, ok_script)

    def broken(run_result):
        raise TypeError("sequence item 0: expected str instance, dict found")
    monkeypatch.setattr(orun, "render_summary", broken)
    sent, send = capture()
    code = orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run, send=send)
    assert code == 1
    assert len(sent) == 1
    assert "보고서 생성 실패: TypeError" in sent[0] and TODAY.isoformat() in sent[0]
    assert "반영 1" in sent[0]


def test_I4_dirty_data_official_blocks_apply(monkeypatch, tmp_path):
    run, calls = wire(monkeypatch, tmp_path, ok_script, dirty=" M data/official/acl.yaml\n?? data/official/x.yaml\n")
    sent, send = capture()
    code = orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run, send=send)
    assert code == 1
    assert "data/official에 스크립트 밖의 변경이 있어 반영하지 않음" in sent[0]
    assert "data/official/acl.yaml" in sent[0] and "data/official/x.yaml" in sent[0]
    assert not (tmp_path / "official" / "acl.yaml").exists()
    assert not (tmp_path / "official" / "checklog.yaml").exists()
    assert calls == [BRANCH, STATUS], "빌드도 커밋도 push도 하지 않는다"


def isolate_prep(monkeypatch, tmp_path):
    """prep이 회귀해 끝까지 달려도 실제 경로·네트워크에 닿지 않게 한다."""
    raw = tmp_path / "raw"
    monkeypatch.setattr(orun, "RAW_DIR", raw)
    monkeypatch.setattr(orun, "WORKLIST_PATH", raw / "worklist.json")
    data_path = tmp_path / "conferences.json"
    data_path.write_text(json.dumps({"conferences": []}), encoding="utf-8")
    monkeypatch.setattr(orun, "DATA_PATH", data_path)
    monkeypatch.setattr(orun, "CHECKLOG_PATH", tmp_path / "checklog.yaml")

    def no_fetch(*a, **k):
        raise AssertionError("네트워크 금지")
    monkeypatch.setattr(orun, "http_fetch", no_fetch)
    return no_fetch


def test_I5_pull_failure_aborts_rebase_and_notifies(monkeypatch, tmp_path):
    fetch = isolate_prep(monkeypatch, tmp_path)
    calls = []

    def run(cmd):
        calls.append(cmd)
        if cmd == BRANCH:
            return Proc(0, out="master\n")
        return Proc(1, err="CONFLICT") if cmd[:2] == ["git", "pull"] else Proc(0)
    sent, send = capture()
    assert orun.prep_run(TODAY, run=run, fetch=fetch, send=send) == 1
    assert ["git", "rebase", "--abort"] in calls
    assert len(sent) == 1 and "git pull" in sent[0]
    assert not (tmp_path / "raw" / "prep.json").exists()


def test_I6_failed_commit_does_not_push(monkeypatch, tmp_path):
    def script(cmd):
        if cmd[:3] == ["git", "diff", "--cached"]:
            return Proc(1)
        if "commit" in cmd:
            return Proc(1, err="Author identity unknown")
        return Proc(0)
    run, calls = wire(monkeypatch, tmp_path, script)
    sent, send = capture()
    code = orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run, send=send)
    assert code == 1
    assert not any(c[:2] == ["git", "push"] for c in calls)
    assert "git commit 실패: Author identity unknown" in sent[0]
    assert "반영 0" in sent[0]


def test_I6_failed_stash_is_reported_not_claimed(monkeypatch, tmp_path):
    def script(cmd):
        if "pytest" in cmd:
            return Proc(1, err="1 failed")
        if cmd[:3] == ["git", "stash", "push"]:
            return Proc(1, err="cannot stash")
        return Proc(0)
    run, calls = wire(monkeypatch, tmp_path, script)
    sent, send = capture()
    assert orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run, send=send) == 1
    assert "git stash 실패: cannot stash" in sent[0]
    assert "git stash에 보관" not in sent[0]


def test_Ma_apply_refuses_off_master(monkeypatch, tmp_path):
    run, calls = wire(monkeypatch, tmp_path, ok_script, branch="feature/x")
    sent, send = capture()
    code = orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run, send=send)
    assert code == 1
    assert "master 브랜치가 아님" in sent[0] and "feature/x" in sent[0]
    assert not (tmp_path / "official" / "acl.yaml").exists()
    assert not (tmp_path / "official" / "checklog.yaml").exists()
    assert calls == [BRANCH]


def test_Ma_prep_refuses_off_master(monkeypatch, tmp_path):
    fetch = isolate_prep(monkeypatch, tmp_path)
    calls = []
    run = lambda cmd: calls.append(cmd) or (Proc(0, out="feature/x\n") if cmd == BRANCH else Proc(0))
    sent, send = capture()
    assert orun.prep_run(TODAY, run=run, fetch=fetch, send=send) == 1
    assert calls == [BRANCH], "pull하지 않는다"
    assert len(sent) == 1 and "master 브랜치가 아님" in sent[0]


def test_Mb_unchanged_items_are_counted_but_not_written(monkeypatch, tmp_path):
    """검토를 건너뛴 그대로인 값은 쓰지 않는다 - replace 타입이 다른 업스트림 날짜를 지우지 않게."""
    run, calls = wire(monkeypatch, tmp_path, ok_script)
    # 이미 사이트에 같은 paper 날짜가 있다 -> 그대로인 항목
    data = {"conferences": [{"abbr": "ACL", "key": "acl", "editions": [
        {"year": 2027, "deadlines": [{"type": "paper", "label": "x", "date": "2027-01-04T23:59:59"}]}]}]}
    (tmp_path / "conferences.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(orun, "official_key", lambda conf: conf.get("key"))
    sent, send = capture()
    orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run, send=send)
    assert not (tmp_path / "official" / "acl.yaml").exists()
    import yaml
    entry = yaml.safe_load((tmp_path / "official" / "checklog.yaml").read_text(encoding="utf-8"))["acl/2027"]
    assert entry["results"]["D"] in ("found", "tba")


def test_Mb_changed_item_written_alongside_unchanged(monkeypatch, tmp_path):
    run, calls = wire(monkeypatch, tmp_path, ok_script)
    path = tmp_path / "raw" / "acl-2027.json"
    ext = json.loads(path.read_text(encoding="utf-8"))
    assert len(ext["items"]) >= 1
    paper = ext["items"][0]
    data = {"conferences": [{"abbr": "ACL", "key": "acl", "editions": [
        {"year": 2027, "deadlines": [{"type": paper["type"], "label": "x", "date": paper["date"][:10] + "T23:59:59"}]}]}]}
    (tmp_path / "conferences.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(orun, "official_key", lambda conf: conf.get("key"))
    o = orun.process_target(target("acl", ["D"]), tmp_path / "raw", data, agree_with([ACL_PAPER]))
    assert [d.get("unchanged") for d in o.approved["deadlines"]] == [True]
    to_write = orun.changed_only(o.approved)
    assert to_write["deadlines"] == [] and to_write["edition"] is None
    new = {"type": "poster", "label": "LBW", "date": "2027-02-01 23:59:59", "evidence": {"url": "u", "raw_text": "r"}}
    mixed = orun.changed_only({"edition": None, "deadlines": [*o.approved["deadlines"], new]})
    assert mixed["deadlines"] == [new]


def test_Md_failed_build_clears_applied(monkeypatch, tmp_path):
    run, calls = wire(monkeypatch, tmp_path, lambda cmd: Proc(1, err="boom") if "pytest" in cmd else Proc(0))
    sent, send = capture()
    orun.apply_run(TODAY, ask=agree_with([ACL_PAPER]), run=run, send=send)
    assert "반영 0" in sent[0] and "[반영]" not in sent[0]
