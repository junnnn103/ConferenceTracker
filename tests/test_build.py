import json
from datetime import date, datetime

from scripts.build import build, enabled_field_ids
from scripts.models import Deadline, Edition, OfficialEdition

FIELDS = [
    {"id": "CV", "label": "CV", "color": "#3b82f6", "enabled": True},
    {"id": "Network", "label": "Network", "color": "#64748b", "enabled": False},
]

REGISTRY = [
    {
        "abbr": "cvpr", "display": "CVPR",
        "full_name": "Computer Vision and Pattern Recognition",
        "grade": "최우수", "ai_specialist": True, "field": "CV",
        "homepage": "https://cvpr.thecvf.com/", "members": None,
        "sources": {"ai_deadlines": "cvpr", "ccfddl": "cvpr"},
    },
    {
        "abbr": "infocom", "display": "INFOCOM", "full_name": "IEEE INFOCOM",
        "grade": "최우수", "ai_specialist": True, "field": "Network",
        "homepage": None, "members": None,
        "sources": {"ai_deadlines": None, "ccfddl": "infocom"},
    },
    {
        "abbr": "hri", "display": "HRI", "full_name": "Human Robot Interaction",
        "grade": "우수", "ai_specialist": True, "field": "CV",
        "homepage": None, "members": None,
        "sources": {"ai_deadlines": None, "ccfddl": None},
    },
]

TODAY = date(2026, 1, 15)


def cvpr_edition():
    return Edition(
        year=2026, date_text="June 3-7, 2026",
        start=date(2026, 6, 3), end=date(2026, 6, 7),
        place="Denver USA", link="https://cvpr.thecvf.com/2026",
        deadlines=[Deadline("paper", "Paper", datetime(2025, 11, 13, 23, 59, 59),
                            "AoE", "ai-deadlines")],
        source="ai-deadlines",
    )


def make_fetchers(hf=None, ccf=None):
    return {
        "ai-deadlines": lambda cid: (hf or {}).get(cid, []),
        "ccfddl": lambda cid: (ccf or {}).get(cid, []),
    }


def test_enabled_field_ids():
    assert enabled_field_ids(FIELDS) == {"CV"}


def test_disabled_field_conferences_are_excluded():
    out = build(REGISTRY, FIELDS, make_fetchers(hf={"cvpr": [cvpr_edition()]}),
                manual={}, scraped={}, today=TODAY)
    assert [c["abbr"] for c in out["conferences"]] == ["CVPR"]
    assert "infocom" not in str(out)


def test_conference_carries_registry_metadata():
    out = build(REGISTRY, FIELDS, make_fetchers(hf={"cvpr": [cvpr_edition()]}),
                manual={}, scraped={}, today=TODAY)
    conf = out["conferences"][0]
    assert conf["abbr"] == "CVPR"
    assert conf["abbr_group"] == "cvpr"
    assert conf["grade"] == "최우수"
    assert conf["ai_specialist"] is True
    assert conf["homepage"] == "https://cvpr.thecvf.com/"
    assert conf["editions"][0]["primary_deadline"] == "2025-11-13T23:59:59"


def test_bk_grade_survives_the_build():
    # bk_grade는 registry.yaml -> build -> JSON까지 그대로 흘러야 한다.
    # null인 학회도 필드 자체는 있어야 한다 - 없으면 프론트가 "BK 목록에
    # 없음"과 "아직 값이 안 채워짐"을 구분하지 못한다.
    registry = [
        {
            "abbr": "cvpr", "display": "CVPR",
            "full_name": "Computer Vision and Pattern Recognition",
            "grade": "최우수", "bk_grade": "S", "ai_specialist": True, "field": "CV",
            "homepage": "https://cvpr.thecvf.com/", "members": None,
            "sources": {"ai_deadlines": "cvpr", "ccfddl": "cvpr"},
        },
        {
            "abbr": "icip", "display": "ICIP", "full_name": "Image Processing",
            "grade": "우수", "bk_grade": None, "ai_specialist": True, "field": "CV",
            "homepage": "https://example.org/", "members": None,
            "sources": {"ai_deadlines": None, "ccfddl": "icip"},
        },
    ]
    out = build(
        registry, FIELDS,
        make_fetchers(hf={"cvpr": [cvpr_edition()]}, ccf={"icip": [cvpr_edition()]}),
        manual={}, scraped={}, today=TODAY,
    )
    by_abbr = {c["abbr"]: c for c in out["conferences"]}
    assert by_abbr["CVPR"]["bk_grade"] == "S"
    assert "bk_grade" in by_abbr["ICIP"]
    assert by_abbr["ICIP"]["bk_grade"] is None


def test_only_the_adjacent_editions_survive():
    # build는 회차를 직전 1개 + 차기 1개로 줄인다. 전부 내보내면 JSON이 부풀고
    # 브라우저가 고르지 말아야 할 오래된 회차까지 후보로 받는다.
    many = [
        Edition(year, "", date(year, 6, 1), date(year, 6, 5), "X", None, [], "ai-deadlines")
        for year in (2023, 2024, 2025, 2026, 2027)
    ]
    out = build(REGISTRY, FIELDS, make_fetchers(hf={"cvpr": many}),
                manual={}, scraped={}, today=TODAY)
    years = [e["year"] for e in out["conferences"][0]["editions"]]
    assert years == [2025, 2026]


def test_conference_without_any_edition_goes_to_unresolved():
    out = build(REGISTRY, FIELDS, make_fetchers(), manual={}, scraped={}, today=TODAY)
    assert out["conferences"] == []
    assert [u["abbr"] for u in out["unresolved"]] == ["CVPR", "HRI"]


def test_manual_supplies_conference_with_no_source_mapping():
    manual = {"hri": [Edition(2026, "March 9-12, 2026", date(2026, 3, 9), date(2026, 3, 12),
                              "Christchurch New Zealand", None,
                              [Deadline("paper", "Full Paper", datetime(2025, 10, 1),
                                        "AoE", "manual")], "manual")]}
    out = build(REGISTRY, FIELDS, make_fetchers(), manual=manual, scraped={}, today=TODAY)
    assert [c["abbr"] for c in out["conferences"]] == ["HRI"]
    assert out["conferences"][0]["editions"][0]["place"] == "Christchurch New Zealand"


def test_scraped_deadlines_are_attached_to_matching_edition():
    scraped = {("cvpr", 2026): [Deadline("poster", "Posters", datetime(2026, 4, 21),
                                         None, "cfp-scrape",
                                         {"raw_text": "x", "url": "y"})]}
    out = build(REGISTRY, FIELDS, make_fetchers(hf={"cvpr": [cvpr_edition()]}),
                manual={}, scraped=scraped, today=TODAY)
    types = [d["type"] for d in out["conferences"][0]["editions"][0]["deadlines"]]
    assert types == ["paper", "poster"]


def test_fields_section_lists_only_enabled_fields():
    out = build(REGISTRY, FIELDS, make_fetchers(hf={"cvpr": [cvpr_edition()]}),
                manual={}, scraped={}, today=TODAY)
    assert out["fields"] == [{"id": "CV", "label": "CV", "color": "#3b82f6"}]


def test_failing_fetcher_does_not_abort_the_build():
    def explode(_):
        raise RuntimeError("network down")

    fetchers = {"ai-deadlines": explode,
                "ccfddl": lambda cid: {"cvpr": [cvpr_edition()]}.get(cid, [])}
    out = build(REGISTRY, FIELDS, fetchers, manual={}, scraped={}, today=TODAY)
    assert [c["abbr"] for c in out["conferences"]] == ["CVPR"]


def test_non_http_homepage_is_dropped_with_warning(capsys):
    # registry.yaml, manual.yaml, ai-deadlines/ccfddl은 모두 공개 PR을 받는
    # 제3자 소스다. javascript: 같은 스킴이 섞여 들어오면 브라우저가 href에
    # 그대로 옮겨 클릭 한 번에 실행되므로, JSON에 실리기 전에 걸러야 한다.
    registry = [{**REGISTRY[0], "homepage": "javascript:alert(1)"}]
    out = build(registry, FIELDS, make_fetchers(hf={"cvpr": [cvpr_edition()]}),
                manual={}, scraped={}, today=TODAY)
    assert out["conferences"][0]["homepage"] is None
    err = capsys.readouterr().err
    assert "CVPR" in err
    assert "javascript:alert(1)" in err


def test_non_http_edition_link_is_dropped_with_warning(capsys):
    edition = cvpr_edition()
    edition.link = "javascript:alert(1)"
    out = build(REGISTRY, FIELDS, make_fetchers(hf={"cvpr": [edition]}),
                manual={}, scraped={}, today=TODAY)
    assert out["conferences"][0]["editions"][0]["link"] is None
    err = capsys.readouterr().err
    assert "CVPR" in err
    assert "javascript:alert(1)" in err


def test_relative_and_protocol_relative_homepage_is_dropped(capsys):
    # docs/app.js의 safeHref는 렌더 시점에 base(현재 페이지 주소)를 붙여
    # new URL()로 해석한다. "//evil.com"은 base의 스킴만 빌려 완전히 다른
    # 사이트로 가는 살아있는 링크가 되고, "evil.com"과 "/relative/path"는
    # 우리 도메인 위의 없는 경로가 된다. 스킴이 아예 없는 이 값들도
    # build 단계에서부터 막아야 한다.
    for bad in ("//evil.com/path", "evil.com", "/relative/path"):
        registry = [{**REGISTRY[0], "homepage": bad}]
        out = build(registry, FIELDS, make_fetchers(hf={"cvpr": [cvpr_edition()]}),
                    manual={}, scraped={}, today=TODAY)
        assert out["conferences"][0]["homepage"] is None, bad
        err = capsys.readouterr().err
        assert "CVPR" in err and bad in err, bad


def test_output_has_generated_at_timestamp():
    out = build(REGISTRY, FIELDS, make_fetchers(hf={"cvpr": [cvpr_edition()]}),
                manual={}, scraped={}, today=TODAY)
    assert "generated_at" in out


def test_combined_row_picks_member_and_uses_its_display_name():
    registry = [{
        "abbr": "iccv/eccv", "display": "ICCV/ECCV", "full_name": "ICCV / ECCV",
        "grade": "최우수", "ai_specialist": True, "field": "CV",
        "homepage": None,
        "members": [
            {"display": "ICCV", "sources": {"ai_deadlines": "iccv", "ccfddl": "iccv"}},
            {"display": "ECCV", "sources": {"ai_deadlines": "eccv", "ccfddl": "eccv"}},
        ],
        "sources": {"ai_deadlines": None, "ccfddl": None},
    }]
    hf = {
        "iccv": [Edition(2027, "", date(2027, 10, 1), date(2027, 10, 6), "", None, [], "ai-deadlines")],
        "eccv": [Edition(2026, "", date(2026, 9, 8), date(2026, 9, 13), "", None, [], "ai-deadlines")],
    }
    out = build(registry, FIELDS, make_fetchers(hf=hf), manual={}, scraped={}, today=TODAY)
    conf = out["conferences"][0]
    assert conf["abbr"] == "ECCV"        # 2026-01-15 기준 차기는 ECCV 2026
    assert conf["abbr_group"] == "iccv/eccv"


# main()이 실제 registry.yaml/네트워크를 타지 않도록 완전히 격리된 픽스처.
# sources가 전부 null이라 fetcher가 호출되지 않고, conf0만 manual로 해소되어
# "부분 실패"(1/5 < 절반)를 결정적으로 재현한다. 활성 학회 수가 바뀌어도
# (task 10처럼 registry.yaml의 sources를 채우는 변경이 와도) 이 테스트는
# 흔들리지 않는다.
_SHRINK_TEST_FIELDS = [{"id": "CV", "label": "CV", "color": "#3b82f6", "enabled": True}]
_SHRINK_TEST_REGISTRY = [
    {"abbr": f"conf{i}", "display": f"CONF{i}", "full_name": "", "grade": "",
     "ai_specialist": False, "field": "CV", "homepage": None, "members": None,
     "sources": {"ai_deadlines": None, "ccfddl": None}}
    for i in range(5)
]
_SHRINK_TEST_MANUAL = {
    "conf0": [Edition(
        year=2024, date_text="Jan 1, 2024", start=date(2024, 1, 1), end=date(2024, 1, 2),
        place="X", link="https://example.com", deadlines=[], source="manual",
    )],
}


def _patch_isolated_build_inputs(monkeypatch, build_module):
    """main()이 실제 data/registry.yaml이나 네트워크를 건드리지 않게 한다."""
    monkeypatch.setattr(build_module, "load_registry", lambda: _SHRINK_TEST_REGISTRY)
    monkeypatch.setattr(build_module, "load_fields", lambda: _SHRINK_TEST_FIELDS)
    monkeypatch.setattr(build_module, "load_manual", lambda path: _SHRINK_TEST_MANUAL)
    monkeypatch.setattr(build_module, "load_scraped", lambda path: {})


def test_shrinking_conferences_below_half_is_rejected(tmp_path, monkeypatch):
    # 기존 JSON이 많은 학회를 가지고 있을 때, 새 실행이 그것의 절반 미만을
    # 내보내면 소스 장애로 보고 기존 파일을 유지한다.
    import scripts.build as build_module

    output_file = tmp_path / "conferences.json"
    monkeypatch.setattr(build_module, "OUTPUT_PATH", output_file)
    _patch_isolated_build_inputs(monkeypatch, build_module)

    # 기존 파일: 40개 학회
    existing = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "fields": [],
        "conferences": [{"abbr": f"CONF{i}", "abbr_group": f"conf{i}", "editions": []}
                        for i in range(40)],
        "unresolved": [],
    }
    output_file.write_text(json.dumps(existing), encoding="utf-8")

    # 새 실행: 1개만 생성 (< 20, 절반의 절반)
    out = build(_SHRINK_TEST_REGISTRY, _SHRINK_TEST_FIELDS, make_fetchers(),
                manual=_SHRINK_TEST_MANUAL, scraped={}, today=TODAY)
    assert len(out["conferences"]) < 20

    # main()이 거부해야 함
    from scripts.build import main
    monkeypatch.setattr("sys.argv", ["build"])
    result = main()
    assert result == 1
    # 파일이 기존 내용 유지
    existing_content = json.loads(output_file.read_text(encoding="utf-8"))
    assert len(existing_content["conferences"]) == 40


def test_allow_shrink_flag_overrides_rejection(tmp_path, monkeypatch):
    # --allow-shrink 플래그가 있으면 학회 수 급감해도 덮어쓴다.
    import scripts.build as build_module

    output_file = tmp_path / "conferences.json"
    monkeypatch.setattr(build_module, "OUTPUT_PATH", output_file)
    _patch_isolated_build_inputs(monkeypatch, build_module)

    # 기존 파일: 40개
    existing = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "fields": [],
        "conferences": [{"abbr": f"CONF{i}", "abbr_group": f"conf{i}", "editions": []}
                        for i in range(40)],
        "unresolved": [],
    }
    output_file.write_text(json.dumps(existing), encoding="utf-8")

    # main()에 --allow-shrink
    from scripts.build import main
    monkeypatch.setattr("sys.argv", ["build", "--allow-shrink"])
    result = main()
    assert result == 0
    # 파일이 새 내용으로 덮어씀
    new_content = json.loads(output_file.read_text(encoding="utf-8"))
    assert len(new_content["conferences"]) < 20


def test_shrink_guard_catches_ai_deadlines_outage_ratio(tmp_path, monkeypatch):
    # 실제 등록 현황을 재현한다: 38개 중 19개는 ai-deadlines 없이 manual/
    # ccfddl만으로 해소되고, 나머지 19개는 ai-deadlines 없이는 전혀 해소되지
    # 않는다. ai-deadlines가 통째로 죽으면(fetcher가 아무것도 못 돌려주면)
    # 정확히 19개만 살아남는다.
    #
    # 절반(0.5) 기준이었다면 "19 * 2 < 38"은 거짓이라 게이트가 조용히
    # 통과해 버렸다 - 바로 이 시나리오가 발견된 버그였다. 0.8 기준은
    # "19 < 38 * 0.8 (=30.4)"가 참이라 이를 잡아낸다.
    import scripts.build as build_module

    output_file = tmp_path / "conferences.json"
    monkeypatch.setattr(build_module, "OUTPUT_PATH", output_file)

    registry = [
        {"abbr": f"resolved{i}", "display": f"RESOLVED{i}", "full_name": "", "grade": "",
         "ai_specialist": False, "field": "CV", "homepage": None, "members": None,
         "sources": {"ai_deadlines": None, "ccfddl": None}}
        for i in range(19)
    ] + [
        {"abbr": f"gone{i}", "display": f"GONE{i}", "full_name": "", "grade": "",
         "ai_specialist": False, "field": "CV", "homepage": None, "members": None,
         "sources": {"ai_deadlines": f"gone{i}", "ccfddl": None}}
        for i in range(19)
    ]
    manual = {
        f"resolved{i}": [Edition(
            year=2024, date_text="Jan 1, 2024", start=date(2024, 1, 1), end=date(2024, 1, 2),
            place="X", link="https://example.com", deadlines=[], source="manual",
        )]
        for i in range(19)
    }
    monkeypatch.setattr(build_module, "load_registry", lambda: registry)
    monkeypatch.setattr(build_module, "load_fields", lambda: _SHRINK_TEST_FIELDS)
    monkeypatch.setattr(build_module, "load_manual", lambda path: manual)
    monkeypatch.setattr(build_module, "load_scraped", lambda path: {})

    # ai-deadlines가 죽었다고 가정한다 - main()이 직접 만드는 fetcher가
    # 이 이름으로 네트워크를 타므로, 여기서 예외를 던지게 바꿔 재현한다.
    # build()는 소스 하나의 실패를 잡아 건너뛰므로(_gather) 네트워크 없이도
    # "ai-deadlines만 죽었을 때" 상황이 결정적으로 재현된다.
    def _dead_aideadlines(conf_id, session):
        raise RuntimeError("ai-deadlines unreachable")

    monkeypatch.setattr(build_module, "fetch_aideadlines", _dead_aideadlines)

    existing = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "fields": [],
        "conferences": [{"abbr": f"C{i}", "abbr_group": f"c{i}", "editions": []}
                        for i in range(38)],
        "unresolved": [],
    }
    output_file.write_text(json.dumps(existing), encoding="utf-8")

    from scripts.build import main
    monkeypatch.setattr("sys.argv", ["build"])
    result = main()

    assert result == 1
    existing_content = json.loads(output_file.read_text(encoding="utf-8"))
    assert len(existing_content["conferences"]) == 38


def test_group_keyed_manual_on_combined_row_is_skipped():
    # 결합 행의 manual 항목이 그룹 키("iccv/eccv")로 적히면 어느 구성원의
    # 회차인지 알 수 없다. 병합하면 엉뚱한 이름표가 붙으므로 버려야 한다.
    # ECCV는 소스로 진짜 차기 회차를 받고, manual은 그보다 이른 날짜를
    # 그룹 키로 제공한다 — 예전 방식(선택 후 병합)이면 이 이른 날짜가
    # 선택을 가로채 ECCV 이름표를 달고 출력에 나타난다.
    registry = [{
        "abbr": "iccv/eccv", "display": "ICCV/ECCV", "full_name": "ICCV / ECCV",
        "grade": "최우수", "ai_specialist": True, "field": "CV",
        "homepage": None,
        "members": [
            {"display": "ICCV", "sources": {"ai_deadlines": "iccv", "ccfddl": "iccv"}},
            {"display": "ECCV", "sources": {"ai_deadlines": "eccv", "ccfddl": "eccv"}},
        ],
        "sources": {"ai_deadlines": None, "ccfddl": None},
    }]

    # 소스: ECCV만 차기 회차를 가짐 (ICCV는 소스 데이터 없음)
    hf = {
        "eccv": [Edition(2026, "", date(2026, 9, 8), date(2026, 9, 13), "", None, [], "ai-deadlines")],
    }

    # manual: 그룹 키("iccv/eccv")로 적힌, ECCV보다 이른 차기 회차
    manual = {"iccv/eccv": [Edition(2026, "", date(2026, 3, 1), date(2026, 3, 6), "", None, [], "manual")]}

    out = build(registry, FIELDS, make_fetchers(hf=hf), manual=manual, scraped={}, today=TODAY)
    conf = out["conferences"][0]
    assert conf["abbr"] == "ECCV"
    starts = [e["start"] for e in conf["editions"]]
    assert "2026-03-01" not in starts  # 그룹 키 manual 회차는 출력에 없어야 함


def test_member_keyed_manual_on_combined_row_is_attributed_correctly():
    # 결합 행의 manual 항목이 구성원 이름("iccv")으로 적히면 그 구성원의
    # 진짜 회차로 취급되어 대표 선택에도 정당하게 참여해야 한다.
    # ICCV는 manual로만 (소스 데이터 없음) ECCV의 소스 회차보다 이른
    # 차기 날짜를 받으므로 ICCV가 대표로 뽑혀야 한다.
    registry = [{
        "abbr": "iccv/eccv", "display": "ICCV/ECCV", "full_name": "ICCV / ECCV",
        "grade": "최우수", "ai_specialist": True, "field": "CV",
        "homepage": None,
        "members": [
            {"display": "ICCV", "sources": {"ai_deadlines": "iccv", "ccfddl": "iccv"}},
            {"display": "ECCV", "sources": {"ai_deadlines": "eccv", "ccfddl": "eccv"}},
        ],
        "sources": {"ai_deadlines": None, "ccfddl": None},
    }]

    # 소스: ECCV만 차기 회차를 가짐
    hf = {
        "eccv": [Edition(2026, "", date(2026, 9, 8), date(2026, 9, 13), "", None, [], "ai-deadlines")],
    }

    # manual: 구성원 이름("iccv")으로 적힌, ECCV보다 이른 차기 회차
    manual = {"iccv": [Edition(2026, "", date(2026, 3, 1), date(2026, 3, 6), "", None, [], "manual")]}

    out = build(registry, FIELDS, make_fetchers(hf=hf), manual=manual, scraped={}, today=TODAY)
    conf = out["conferences"][0]
    assert conf["abbr"] == "ICCV"
    starts = [e["start"] for e in conf["editions"]]
    assert "2026-03-01" in starts  # ICCV의 manual 회차가 표시되어야 함


def test_scraped_by_member_name_attaches_to_combined_row():
    # 결합 행의 scraped 데이터는 abbr_group("iccv/eccv")이 아니라
    # 선택된 구성원 이름("eccv")으로 keyed되어야 한다.
    registry = [{
        "abbr": "iccv/eccv", "display": "ICCV/ECCV", "full_name": "ICCV / ECCV",
        "grade": "최우수", "ai_specialist": True, "field": "CV",
        "homepage": None,
        "members": [
            {"display": "ICCV", "sources": {"ai_deadlines": "iccv", "ccfddl": "iccv"}},
            {"display": "ECCV", "sources": {"ai_deadlines": "eccv", "ccfddl": "eccv"}},
        ],
        "sources": {"ai_deadlines": None, "ccfddl": None},
    }]

    hf = {
        "iccv": [Edition(2027, "", date(2027, 10, 1), date(2027, 10, 6), "", None, [], "ai-deadlines")],
        "eccv": [Edition(2026, "", date(2026, 9, 8), date(2026, 9, 13), "", None, [], "ai-deadlines")],
    }

    # scraped는 "eccv" (선택된 구성원)로 keyed
    scraped = {("eccv", 2026): [Deadline("workshop", "Workshops", datetime(2026, 8, 1),
                                         None, "cfp-scrape", {"raw_text": "x", "url": "y"})]}

    out = build(registry, FIELDS, make_fetchers(hf=hf), manual={}, scraped=scraped, today=TODAY)
    conf = out["conferences"][0]
    assert conf["abbr"] == "ECCV"
    # scraped deadline이 붙음
    types = [d["type"] for d in conf["editions"][0]["deadlines"]]
    assert "workshop" in types


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
