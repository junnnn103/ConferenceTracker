"""공식 사이트 페이지 수집 (설계 §6). LLM을 쓰지 않는다.

1 홈페이지와 2 회차 주소를 둘 다 받는다. 하나가 열렸다고 멈추지 않는다 -
ACL의 홈페이지 www.aclweb.org는 열리지만 2027 일정은 2027.aclweb.org에만
있다. 받은 페이지 어디에도 대상 연도가 없으면 needs_alternate로 표시하고,
3 Hermes가 찾은 대체 주소를 --urls로 받아 다시 수집한다.
"""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).parents[1]
RAW_DIR = ROOT / "data" / "official" / "raw"
WORKLIST_PATH = RAW_DIR / "worklist.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130 Safari/537.36")
MAX_PAGES = 8
REQUEST_GAP_SECONDS = 1.0
KEYWORDS = ("date", "deadline", "call", "cfp", "paper", "poster", "late-breaking", "lbw",
            "workshop", "important")
# 공식 사이트를 읽는 것이 목적이다. 마감 모음 사이트는 받지 않는다.
AGGREGATOR_HOSTS = ("ccfddl.com", "ccfddl.top", "ccfddl.github.io", "huggingface.co",
                    "aideadlin.es", "wikicfp.com", "conferenceindex.org", "github.com",
                    "raw.githubusercontent.com")
_SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".ics", ".css", ".js")
_HREF = re.compile(r"""<a\s[^>]*?href\s*=\s*["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)

Fetch = Callable[[str], tuple]


@dataclass
class FetchResult:
    key: str
    year: int
    access: str
    pages: list[tuple[str, str]]
    attempts: list[dict]
    year_found: bool


def html_to_text(html: str) -> str:
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html or "")
    t = re.sub(r"(?i)<br\s*/?>|</(p|li|h[1-6]|tr|div|section|td|th|dt|dd)>", "\n", t)
    t = unescape(re.sub(r"(?s)<[^>]+>", " ", t))
    lines = (" ".join(line.split()) for line in t.splitlines())
    return "\n".join(line for line in lines if line)


def extract_links(html: str, base: str) -> list[tuple[str, str]]:
    out = []
    for href, inner in _HREF.findall(html or ""):
        url = urljoin(base, href.strip()).split("#")[0]
        anchor = " ".join(re.sub(r"(?s)<[^>]+>", " ", unescape(inner)).split())
        out.append((url, anchor))
    return out


def is_allowed_url(url: str) -> bool:
    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not u.netloc:
        return False
    host = u.netloc.lower().split(":")[0]
    return not any(host == h or host.endswith("." + h) for h in AGGREGATOR_HOSTS)


def _wanted(url: str, anchor: str, host: str) -> bool:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or u.netloc != host:
        return False
    if u.path.lower().endswith(_SKIP_EXT):
        return False
    hay = (u.path + " " + anchor).lower()
    return any(k in hay for k in KEYWORDS)


def _dedupe(urls: Iterable[str]) -> list[str]:
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _unique_pages(pages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen, out = set(), []
    for url, text in pages:
        if url not in seen:
            seen.add(url)
            out.append((url, text))
    return out


def crawl(start_urls: list[str], fetch: Fetch, max_pages: int = MAX_PAGES, seen: set | None = None):
    queue = list(start_urls)
    seen = set() if seen is None else seen
    pages: list[tuple[str, str]] = []
    attempts: list[dict] = []
    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        status, html = fetch(url)
        attempts.append({"url": url, "status": status})
        if status != 200 or not html:
            continue
        pages.append((url, html_to_text(html)))
        host = urlparse(url).netloc
        for link, anchor in extract_links(html, url):
            if link not in seen and _wanted(link, anchor, host):
                queue.append(link)
    return pages, attempts


def fetch_target(target: dict, fetch: Fetch, extra_urls: Iterable[str] = ()) -> FetchResult:
    year = int(target["year"])
    has_year = lambda text: str(year) in text
    home, edition = target.get("homepage"), target.get("edition_link")
    home = home if home and is_allowed_url(home) else None
    edition = edition if edition and is_allowed_url(edition) else None
    seen: set = set()
    pages: list[tuple[str, str]] = []
    attempts: list[dict] = []
    # 회차 사이트를 먼저, 따로 받는다. 학회 본부 사이트의 링크가 쪽수를
    # 다 써서 회차 사이트의 마감 페이지가 밀리지 않게 한다.
    if edition:
        budget = MAX_PAGES - 2 if home and home != edition else MAX_PAGES
        pages, attempts = crawl([edition], fetch, budget, seen)
    if home and home != edition:
        more, more_attempts = crawl([home], fetch, MAX_PAGES - len(pages), seen)
        pages += more
        attempts += more_attempts
    extra = _dedupe(u for u in extra_urls if is_allowed_url(u))

    if extra:
        more, more_attempts = crawl(extra, fetch, MAX_PAGES, seen)
        attempts += more_attempts
        merged = more + [p for p in pages if has_year(p[1])]
        pages = _unique_pages(merged)[:MAX_PAGES]
        found = any(has_year(text) for _, text in pages)
        access = "via_alternate" if found else "blocked"
    else:
        found = any(has_year(text) for _, text in pages)
        home_ok = any(a["url"] == target.get("homepage") and a["status"] == 200 for a in attempts)
        if not found:
            access = "needs_alternate"
        elif home_ok:
            access = "ok"
        else:
            access = "via_edition_link"
    return FetchResult(str(target["key"]), year, access, pages, attempts, found)


def write_result(result: FetchResult, raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{result.key}-{result.year}"
    body = "".join(f"===== {url} =====\n{text}\n\n" for url, text in result.pages)
    (raw_dir / f"{stem}.txt").write_text(body, encoding="utf-8")
    meta = {"key": result.key, "year": result.year, "access": result.access,
            "year_found": result.year_found, "attempts": result.attempts}
    (raw_dir / f"{stem}.fetch.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def http_fetch(url: str):
    import requests

    time.sleep(REQUEST_GAP_SECONDS)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True)
    except requests.RequestException as exc:
        return type(exc).__name__, None
    if r.status_code != 200:
        return r.status_code, None
    if "html" not in r.headers.get("content-type", "") and "text" not in r.headers.get("content-type", ""):
        return "not_html", None
    return 200, r.text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worklist", type=Path, default=WORKLIST_PATH)
    parser.add_argument("--target", nargs=2, metavar=("KEY", "YEAR"))
    parser.add_argument("--urls", nargs="*", default=[])
    args = parser.parse_args()

    worklist = json.loads(args.worklist.read_text(encoding="utf-8"))
    if args.target:
        key, year = args.target[0], int(args.target[1])
        targets = [t for t in worklist if t["key"] == key and int(t["year"]) == year]
        if not targets:
            print(f"대상 목록에 없음: {key} {year}", file=sys.stderr)
            return 1
    else:
        targets = worklist

    summary = []
    for target in targets:
        result = fetch_target(target, http_fetch, args.urls if args.target else ())
        write_result(result, RAW_DIR)
        summary.append({"key": result.key, "year": result.year, "access": result.access,
                        "pages": len(result.pages)})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
