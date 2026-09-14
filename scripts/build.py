"""빌드 엔트리포인트: data/ + 공개 소스 -> docs/data/conferences.json

네트워크 호출은 주입 가능한 fetcher로 감쌌다. 테스트가 네트워크 없이
전체 파이프라인을 돌릴 수 있어야 하기 때문이다.

한 소스가 죽어도 빌드는 계속한다. 사이트가 어제 데이터로라도 떠 있는 편이
아예 안 뜨는 것보다 낫다.
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml

from scripts.bootstrap_registry import load_registry
from scripts.merge import apply_scraped, merge_by_year, pick_member, select_editions
from scripts.models import Conference, Edition
from scripts.sources.aideadlines import fetch_aideadlines
from scripts.sources.ccfddl import fetch_ccfddl
from scripts.sources.manual import load_manual
from scripts.estimate import placeholder_edition, typical_month
from scripts.sources.scraped import load_scraped

ROOT = Path(__file__).parents[1]
FIELDS_PATH = ROOT / "data" / "fields.yaml"
MANUAL_PATH = ROOT / "data" / "manual.yaml"
SCRAPED_DIR = ROOT / "data" / "scraped"
OUTPUT_PATH = ROOT / "docs" / "data" / "conferences.json"

TZ_UTC = timezone.utc  # 표시는 클라이언트가 하므로 생성 시각만 UTC로 남긴다

ALLOWED_LINK_SCHEMES = {"http", "https"}
_ABSOLUTE_HTTP_RE = re.compile(r"^https?://", re.IGNORECASE)


def _sanitize_link(url: str | None, abbr: str, field_name: str) -> str | None:
    """절대 http/https 주소가 아니면 버린다.

    homepage와 회차 link는 registry.yaml, manual.yaml, 그리고 ai-deadlines/
    ccfddl 같은 제3자 저장소에서 온다 - 전부 공개 PR을 받는 곳이다.
    javascript: 같은 값이 그대로 conferences.json에 실리면, 브라우저가
    href에 곧이곧대로 옮겨 클릭 한 번에 실행된다.

    스킴 자체가 없는 값("//evil.com", "evil.com", "/relative/path")도 함께
    막는다. docs/app.js의 safeHref가 렌더 시점에 base(현재 페이지 주소)를
    붙여 new URL()로 해석하는데, 이런 값은 base의 스킴/호스트를 빌려
    "//evil.com"은 완전히 다른 사이트로 가는 살아있는 링크가, "evil.com"과
    "/relative/path"는 우리 도메인 위의 없는 경로가 되어 버린다. 이
    프로젝트의 링크는 항상 절대 주소이므로 여기서도 같은 기준으로 미리
    걸러야 build와 render 두 방어선의 기준이 어긋나지 않는다.

    조용히 지우면 오타를 지운 것처럼 보이므로 stderr에 경고를 남긴다.
    """
    if not url:
        return url
    valid = bool(_ABSOLUTE_HTTP_RE.match(url))
    if valid:
        try:
            valid = urlparse(url).scheme.lower() in ALLOWED_LINK_SCHEMES
        except ValueError:
            valid = False
    if not valid:
        print(f"경고: {abbr}의 {field_name}에 허용되지 않는 스킴이 있어 제거합니다: {url}",
              file=sys.stderr)
        return None
    return url


def _fill_estimates(
    selected: list, all_editions: list, today, *, combined: bool
) -> dict | None:
    """비어 있는 개최일에 예년 기준 월을 붙인다. 무엇을 추정했는지 돌려준다.

    두 경우가 있다. 회차는 있는데 개최일이 없으면 그 회차에 월만 붙이고,
    마지막 회차까지 전부 지났으면 다음 회차 자리표시자를 만들어 넣는다.

    결합 행은 두 번째를 하지 않는다 - ECCV 2026 다음은 ECCV 2028이 아니라
    ICCV 2027이라, 연도도 이름도 여기서 정할 수 없다.
    """
    upcoming = [e for e in selected if not (e.end or e.start)]
    for edition in upcoming:
        month = typical_month([e for e in all_editions if e.year != edition.year])
        if month is not None:
            edition.estimated_month = month
            return {"year": edition.year, "month": month, "kind": "개최일 미정"}

    if combined:
        return None
    latest_end = max(
        (e.end or e.start for e in selected if (e.end or e.start)), default=None
    )
    if latest_end is None or latest_end >= today:
        return None
    placeholder = placeholder_edition(all_editions, today)
    if placeholder is None:
        return None
    selected.append(placeholder)
    return {"year": placeholder.year, "month": placeholder.estimated_month,
            "kind": "차기 회차 미공개"}


def load_fields(path: Path = FIELDS_PATH) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["fields"]


def enabled_field_ids(fields: list[dict]) -> set[str]:
    return {f["id"] for f in fields if f.get("enabled")}


def _previous_conference_count(path: Path) -> int:
    """이미 발행된 JSON의 학회 수. 읽을 수 없으면 0으로 본다."""
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return len(payload.get("conferences") or [])


def _gather(source_ids: dict, fetchers: dict, abbr: str) -> dict[str, list[Edition]]:
    """소스별 회차 목록을 모은다. 실패한 소스는 건너뛴다."""
    by_source: dict[str, list[Edition]] = {}
    for key, source_name in (("ai_deadlines", "ai-deadlines"), ("ccfddl", "ccfddl")):
        conf_id = (source_ids or {}).get(key)
        if not conf_id:
            continue
        try:
            by_source[source_name] = fetchers[source_name](conf_id) or []
        except Exception as exc:  # 한 소스의 실패가 빌드 전체를 막지 않게 한다
            print(f"경고: {abbr}의 {source_name} 조회 실패: {exc}", file=sys.stderr)
    return by_source


def build(
    registry: list[dict],
    fields: list[dict],
    fetchers: dict,
    manual: dict[str, list[Edition]],
    scraped: dict[tuple[str, int], list],
    today: date,
) -> dict:
    active_fields = enabled_field_ids(fields)
    conferences: list[dict] = []
    unresolved: list[dict] = []
    # 추정으로 채운 칸. 매주 갱신 때 진짜 일정이 올라왔는지 보라고 출력한다.
    estimated: list[dict] = []

    for entry in registry:
        if entry.get("field") not in active_fields:
            continue

        abbr_group = entry["abbr"]
        display = entry.get("display") or abbr_group
        homepage = entry.get("homepage")
        manual_editions = manual.get(abbr_group, [])

        if entry.get("members"):
            # 결합 행: 구성원을 각각 조회한 뒤 차기 회차가 이른 쪽을 대표로 삼는다.
            per_member: dict[str, list[Edition]] = {}
            member_homepages: dict[str, str] = {}
            for member in entry["members"]:
                by_source = _gather(member.get("sources"), fetchers, abbr_group)
                # 결합 행의 manual은 구성원 이름으로 적는다(예: slt, asru).
                # 그 구성원의 진짜 회차이므로 대표 선택에도 정당하게 참여한다.
                member_manual = manual.get(member["display"].lower())
                if member_manual:
                    by_source["manual"] = member_manual
                per_member[member["display"]] = list(merge_by_year(by_source).values())
                if member.get("homepage"):
                    member_homepages[member["display"]] = member["homepage"]
            chosen, editions = pick_member(per_member, today)
            if chosen:
                display = chosen
                # 화면에 뜨는 이름이 구성원 이름(ECCV 등)이므로, 그 구성원의
                # 홈페이지가 있으면 그것을 쓴다. 없으면 행 전체의 홈페이지로
                # 폴백한다 — 안 그러면 ECCV를 눌렀는데 CVF 대문(양쪽 공통
                # 상위 페이지)이나 ICCV 홈페이지가 뜨는, CHI/SIGCHI와 같은
                # 종류의 오류가 난다.
                homepage = member_homepages.get(chosen) or homepage
            if manual_editions:
                # 그룹 키로 적힌 항목은 어느 구성원의 회차인지 알 수 없다.
                # 합치면 다른 구성원 이름표가 붙으므로 버리고 알린다.
                print(f"경고: {abbr_group}은 결합 행입니다. manual 항목을 구성원 이름"
                      f"(예: {entry['members'][0]['display'].lower()})으로 적으세요. "
                      "그룹 키 항목은 무시합니다.", file=sys.stderr)
        else:
            by_source = _gather(entry.get("sources"), fetchers, abbr_group)
            if manual_editions:
                by_source["manual"] = manual_editions
            editions = list(merge_by_year(by_source).values())

        selected = select_editions(editions, today)
        # 결합 행의 abbr_group("iccv/eccv")은 파일명이 될 수 없으므로 선택된
        # 구성원 이름으로 먼저 찾고, 비결합 행을 위해 abbr_group으로 폴백한다.
        member_key = display.lower()
        selected = [
            apply_scraped(
                e,
                scraped.get((member_key, e.year))
                or scraped.get((abbr_group, e.year), []),
            )
            for e in selected
        ]

        if not selected:
            unresolved.append({"abbr": display, "reason": "소스에 회차 정보가 없음"})
            continue

        # 확정 일정이 없는 자리에 예년 기준 개최 월을 채운다. 추정은 언제나
        # 마지막 단계다 - 소스가 준 값은 이미 selected에 들어와 있고, 여기서는
        # 비어 있는 칸만 메운다. 다음 주 갱신에서 진짜 일정이 올라오면 그쪽이
        # 그대로 이긴다.
        estimated_note = _fill_estimates(
            selected, editions, today, combined=bool(entry.get("members")),
        )
        if estimated_note:
            estimated.append({"abbr": display, **estimated_note})

        homepage = _sanitize_link(homepage, display, "homepage")
        for edition in selected:
            edition.link = _sanitize_link(edition.link, display, f"{edition.year}년 CFP 링크")

        conferences.append(Conference(
            abbr=display,
            abbr_group=abbr_group,
            full_name=entry.get("full_name") or "",
            grade=entry.get("grade") or "",
            bk_grade=entry.get("bk_grade"),
            ai_specialist=bool(entry.get("ai_specialist")),
            field=entry["field"],
            homepage=homepage,
            editions=selected,
        ).to_dict())

    return {
        "generated_at": datetime.now(TZ_UTC).isoformat(),
        "fields": [
            {"id": f["id"], "label": f["label"], "color": f["color"]}
            for f in fields if f.get("enabled")
        ],
        "conferences": conferences,
        "unresolved": unresolved,
        "estimated": estimated,
    }


def main() -> int:
    import requests

    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-shrink", action="store_true",
                        help="학회 수가 이전의 80% 미만으로 줄어도 기존 파일을 덮어쓴다")
    args = parser.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = "conference-manager (github actions)"

    fetchers = {
        "ai-deadlines": lambda cid: fetch_aideadlines(cid, session),
        "ccfddl": lambda cid: fetch_ccfddl(cid, session),
    }

    result = build(
        registry=load_registry(),
        fields=load_fields(),
        fetchers=fetchers,
        manual=load_manual(MANUAL_PATH),
        scraped=load_scraped(SCRAPED_DIR),
        today=date.today(),
    )

    if not result["conferences"]:
        # 두 소스가 모두 죽은 경우. 기존 JSON을 덮어쓰지 않는다.
        print("학회를 하나도 만들지 못했습니다. 기존 파일을 유지합니다.", file=sys.stderr)
        return 1

    previous = _previous_conference_count(OUTPUT_PATH)
    current = len(result["conferences"])
    # 절반(0.5) 기준은 실제로 가장 흔한 장애를 놓친다. 38개 학회 중 19개는
    # ai-deadlines 없이 ccfddl만으로도 해소되므로, ai-deadlines가 통째로
    # 죽으면 정확히 19개가 살아남는다 - "19 * 2 < 38"은 거짓이라 게이트를
    # 그냥 통과해 버리고, 나머지 19개가 unresolved로 조용히 덮어써진다.
    # 0.8을 기준으로 하면 이 경우(19/38 = 0.5)도 잡아낸다. 이만큼 줄어드는
    # 정당한 축소(학회가 실제로 여럿 종료되는 등)는 드물고, 그런 경우는
    # --allow-shrink로 의도를 명시하면 된다.
    if previous and current < previous * 0.8 and not args.allow_shrink:
        print(f"학회 수가 {previous}개에서 {current}개로 급감했습니다. "
              "소스 장애로 보여 기존 파일을 유지합니다.", file=sys.stderr)
        print("의도한 축소라면 --allow-shrink 를 붙여 다시 실행하세요.", file=sys.stderr)
        return 1

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"학회 {len(result['conferences'])}개, 미확인 {len(result['unresolved'])}개")
    for item in result["unresolved"]:
        print(f"  미확인: {item['abbr']} - {item['reason']}", file=sys.stderr)
    # 추정은 임시값이다. 매주 갱신 때 진짜 일정이 올라왔는지 확인하라고
    # 목록으로 남긴다 - 조용히 들어가면 확정 일정처럼 굳어 버린다.
    if result["estimated"]:
        print(f"예년 기준으로 추정한 개최월 {len(result['estimated'])}건 "
              "(확정 일정이 올라오면 자동으로 대체됨):")
        for item in result["estimated"]:
            print(f"  추정: {item['abbr']} {item['year']}년 {item['month']}월 "
                  f"- {item['kind']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
