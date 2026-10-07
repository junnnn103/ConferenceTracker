from scripts.fetch_pages import FetchResult, fetch_target, is_allowed_url, write_result
from scripts.validate_official import load_pages


def page(body, links=()):
    anchors = "".join(f'<a href="{href}">{text}</a>' for href, text in links)
    return f"<html><head><title>T</title><script>var x=1;</script></head><body>{body}{anchors}</body></html>"


def fake(site):
    calls = []

    def fetch(url):
        calls.append(url)
        return site.get(url, (404, None))

    fetch.calls = calls
    return fetch


TARGET = {"key": "chi", "year": 2027, "homepage": "https://chi.acm.org/",
          "edition_link": "https://chi2027.acm.org/"}


def test_blocked_homepage_falls_back_to_edition_link():
    site = {
        "https://chi.acm.org/": (403, None),
        "https://chi2027.acm.org/": (200, page("CHI 2027 Pittsburgh", [("/authors/papers/", "Papers")])),
        "https://chi2027.acm.org/authors/papers/": (200, page("Paper submission deadline 10 September 2026")),
    }
    r = fetch_target(TARGET, fake(site))
    assert r.access == "via_edition_link"
    assert [u for u, _ in r.pages] == ["https://chi2027.acm.org/", "https://chi2027.acm.org/authors/papers/"]
    assert "var x" not in r.pages[0][1], "script는 버린다"


def test_open_homepage_without_target_year_needs_alternate():
    """ACL의 aclweb.org처럼 본부 사이트는 열리지만 그 연도 정보가 없다."""
    target = {"key": "acl", "year": 2027, "homepage": "https://www.aclweb.org/", "edition_link": None}
    site = {"https://www.aclweb.org/": (200, page("Association for Computational Linguistics 2025 news"))}
    r = fetch_target(target, fake(site))
    assert r.access == "needs_alternate" and not r.year_found


def test_both_homepage_and_edition_link_are_fetched():
    target = {"key": "acl", "year": 2027, "homepage": "https://www.aclweb.org/",
              "edition_link": "https://2027.aclweb.org/"}
    site = {"https://www.aclweb.org/": (200, page("ACL portal")),
            "https://2027.aclweb.org/": (200, page("ACL 2027 Kyoto"))}
    r = fetch_target(target, fake(site))
    assert r.access == "ok" and r.year_found


def test_crawl_follows_only_same_host_keyword_links_up_to_eight():
    links = [(f"/calls/p{i}/", "Call for Papers") for i in range(12)]
    links += [("https://other.org/dates/", "Important dates"), ("/about/", "About us"), ("/dates.pdf", "Dates")]
    site = {"https://chi2027.acm.org/": (200, page("CHI 2027", links))}
    for i in range(12):
        site[f"https://chi2027.acm.org/calls/p{i}/"] = (200, page(f"page {i} 2027"))
    fetch = fake(site)
    r = fetch_target({**TARGET, "homepage": None}, fetch)
    assert len(r.pages) == 8
    assert not any("other.org" in u or "about" in u or u.endswith(".pdf") for u in fetch.calls)


def test_alternate_urls_skip_aggregators():
    site = {"https://s2027.siggraph.org/": (200, page("SIGGRAPH 2027"))}
    fetch = fake(site)
    target = {"key": "siggraph", "year": 2027, "homepage": "https://www.siggraph.org/", "edition_link": None}
    r = fetch_target(target, fetch, ["https://ccfddl.com/conf/siggraph", "https://s2027.siggraph.org/"])
    assert r.access == "via_alternate"
    assert "https://ccfddl.com/conf/siggraph" not in fetch.calls


def test_alternate_that_still_lacks_the_year_is_blocked():
    site = {"https://x.org/": (200, page("nothing here"))}
    target = {"key": "x", "year": 2027, "homepage": None, "edition_link": None}
    assert fetch_target(target, fake(site), ["https://x.org/"]).access == "blocked"


def test_is_allowed_url():
    assert is_allowed_url("https://2027.aclweb.org/")
    assert not is_allowed_url("javascript:alert(1)")
    assert not is_allowed_url("https://huggingface.co/spaces/huggingface/ai-deadlines")
    assert not is_allowed_url("https://github.com/ccfddl/ccf-deadlines")


def test_write_result_roundtrips_through_load_pages(tmp_path):
    r = FetchResult("acl", 2027, "ok", [("https://a/", "alpha 2027"), ("https://b/", "beta")],
                    [{"url": "https://a/", "status": 200}], True)
    write_result(r, tmp_path)
    pages = load_pages((tmp_path / "acl-2027.txt").read_text(encoding="utf-8"))
    assert pages["https://a/"].strip() == "alpha 2027"
    assert (tmp_path / "acl-2027.fetch.json").exists()


def test_edition_site_is_not_starved_by_homepage_links():
    home_links = [(f"/news/call{i}/", "Call for Papers") for i in range(10)]
    site = {
        "https://soc.org/": (200, page("Society 2027", home_links)),
        "https://ed.org/": (200, page("ED 2027", [("/calls/", "Calls")])),
        "https://ed.org/calls/": (200, page("Calls 2027", [("/calls/main/", "Main track call")])),
        "https://ed.org/calls/main/": (200, page("Paper deadline 2027")),
    }
    for i in range(10):
        site[f"https://soc.org/news/call{i}/"] = (200, page(f"news {i} 2027"))
    target = {"key": "ed", "year": 2027, "homepage": "https://soc.org/", "edition_link": "https://ed.org/"}
    r = fetch_target(target, fake(site))
    assert "https://ed.org/calls/main/" in [u for u, _ in r.pages]
    assert len(r.pages) <= 8


def test_alternate_equal_to_edition_link_is_fetched_once():
    site = {"https://ed.org/": (200, page("ED 2027"))}
    fetch = fake(site)
    target = {"key": "ed", "year": 2027, "homepage": None, "edition_link": "https://ed.org/"}
    r = fetch_target(target, fetch, ["https://ed.org/"])
    assert fetch.calls.count("https://ed.org/") == 1
    assert [u for u, _ in r.pages] == ["https://ed.org/"]
    assert r.access == "via_alternate"
