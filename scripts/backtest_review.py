"""검토자 역검증 (설계 §7a). 실제 Claude를 부른다 - 단위 테스트가 아니다."""

import json
import sys
from pathlib import Path

import argparse

from scripts.review_official import REVIEW_MODEL, ask_claude, review
from scripts.validate_official import load_pages

ROOT = Path(__file__).parents[1]
CASES = ROOT / "tests" / "fixtures" / "official" / "backtest_cases.json"


def pages_for(path: Path, url: str) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    pages = load_pages(text)
    # 섹션 머리줄이 없는 옛 scraped 파일은 파일 전체를 그 주소의 본문으로 본다.
    return pages if url in pages else {url: text}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=REVIEW_MODEL)
    args = parser.parse_args()
    ask = lambda prompt: ask_claude(prompt, model=args.model)
    print(f"검토 모델: {args.model}")
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    mismatches = 0
    for case in cases:
        claim = case["claim"]
        pages = pages_for(ROOT / case["pages"], claim["url"])
        item = {"type": claim["type"], "label": "-", "date": f"{claim['date']} 23:59:59",
                "evidence": {"raw_text": claim["raw_text"], "url": claim["url"]}}
        approved, held = review({"edition": None, "deadlines": [item]}, pages,
                                case["conference"], case["year"], None, ask=ask)
        got = "pass" if approved["deadlines"] else "hold"
        ok = got == case["expect"]
        mismatches += not ok
        detail = "" if not held else f"  {held[0]['reasons']}  {held[0]['review']}"
        print(f"{'OK ' if ok else 'BAD'} {case['case']:45} 기대 {case['expect']:4} 결과 {got:4}{detail}")
    print(f"\n{len(cases) - mismatches}/{len(cases)} 일치")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
