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
    assert ask.prompts == [] and approved["deadlines"] == [{**NOTICE, "unchanged": True}]


def test_unchanged_edition_is_marked_and_changed_item_is_not():
    edition = {"date_text": "May 10-14, 2027", "start": "2027-05-10", "end": "2027-05-14", "place": "Pittsburgh, USA",
               "evidence": {"url": URL, "raw_text": "x"}}
    current = {"start": "2027-05-10", "end": "2027-05-14", "place": "Pittsburgh, USA", "deadlines": []}
    approved, held = ro.review({"edition": edition, "deadlines": [NOTICE]}, {URL: PAGE}, "CHI", 2027, current,
                               ask=asker(json.dumps(AGREE)))
    assert approved["edition"] == {**edition, "unchanged": True}
    assert approved["deadlines"] == [NOTICE] and "unchanged" not in approved["deadlines"][0]


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


def test_empty_excerpt_is_not_reviewed():
    """추출이 실패하면 검토하지 않는다 (추측만으로 일치할 수 있으므로)."""
    ask = asker(json.dumps(AGREE))
    # URL이 pages에 없으면 excerpt가 비어있다.
    accepted = {"edition": None, "deadlines": [NOTICE]}
    approved, held = ro.review(accepted, {}, "CHI", 2027, None, ask=ask)
    assert approved["deadlines"] == []
    assert held[0]["item"] == NOTICE and held[0]["reasons"] == ["no_excerpt"]
    assert ask.prompts == [], "ask should never be called for empty excerpt"


def test_malformed_reviewer_answer_does_not_crash():
    """잘못된 리뷰 답은 예외를 일으키지 않고 보류된다."""
    # 비문자열 답 - parse_review가 None을 반환해야 함
    ask = asker(123)
    approved, held = ro.review({"edition": None, "deadlines": [NOTICE]}, {URL: PAGE}, "CHI", 2027, None, ask=ask)
    assert approved["deadlines"] == []
    assert held[0]["reasons"] == ["unparseable_review"]

    # 해시 불가능한 what 필드 - 비교가 안전해야 함
    ask = asker(json.dumps({**AGREE, "what": ["workshop_acceptance"]}))
    approved, held = ro.review({"edition": None, "deadlines": [NOTICE]}, {URL: PAGE}, "CHI", 2027, None, ask=ask)
    assert approved["deadlines"] == []
    # what가 리스트이므로 set에서 제외되거나 불일치로 잡혀야 함
    assert len(held) > 0 and "what:" in str(held[0]["reasons"])
