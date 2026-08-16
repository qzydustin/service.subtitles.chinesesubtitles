#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""External service health check (lightweight smoke test).

The addon depends on two sites outside our control: SubHD and Zimuku. This
script verifies each with minimal requests, including whether parsing still
holds after site redesigns.

Usage:
    python3 tests/test_external_health.py              # light checks, no file downloads
    python3 tests/test_external_health.py --full       # includes real subtitle downloads
    python3 tests/test_external_health.py --only subhd/download-api

pytest:
    pytest tests/test_external_health.py -k light
    CHINESESUB_FULL=1 pytest tests/test_external_health.py
"""
import argparse
import os
import sys
import tempfile
import time

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIB_DIR = os.path.join(BASE_DIR, "resources", "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

from core.http import make_session
from core.models import Work, WorkQuery
from core.service import resolve_work, search_all
from core.subhd import SubhdProvider
from core.zimuku import ZimukuProvider

# Fixed sample (Inception, 2010); every check is independent of the others.
WORK_QUERY = "盗梦空间"
# Inception's Douban subject id: SubHD serves the work page under it directly
DOUBAN_INCEPTION = "3541415"
SUBHD_SID = "HbupDV"          # a long-lived subtitle entry

CHECKS = []  # (name, func, full_only)


def check(name, full=False):
    def deco(fn):
        CHECKS.append((name, fn, full))
        return fn
    return deco


@check("zimuku/find-works")
def check_zimuku_find_works():
    provider = ZimukuProvider()
    works = provider.find_works(WorkQuery(title=WORK_QUERY))
    assert works, "Zimuku work search returned nothing (incl. captcha retries)"
    return "%d works, e.g. %s" % (len(works), works[0].title)


@check("subhd/direct-page")
def check_subhd_direct_page():
    """SubHD serves work pages under Douban subject ids (/d/{id})."""
    provider = SubhdProvider()
    work = Work(title="盗梦空间 Inception",
                anchors={"subhd": ["/d/%s" % DOUBAN_INCEPTION]})
    results = provider.search(WorkQuery(title=WORK_QUERY), work)
    assert results, "/d/{douban id} page yielded no subtitles (site redesign?)"
    return "%d subtitles (/d/%s)" % (len(results), DOUBAN_INCEPTION)


@check("subhd/download-api")
def check_subhd_download_api():
    """Verify the post-2026-08 flow: prepare-download still grants a temp page."""
    session = make_session(retries=0)
    detail = "https://subhd.tv/a/%s" % SUBHD_SID
    session.get(detail, timeout=10)
    res = session.post(
        "https://subhd.tv/api/sub/prepare-download",
        json={"sid": SUBHD_SID},
        headers={"Referer": detail, "X-Requested-With": "XMLHttpRequest"},
        timeout=10,
    )
    assert res.status_code == 200, "HTTP %s" % res.status_code
    data = res.json()
    assert data.get("success") and data.get("url"), "unexpected API reply: %r" % (data,)
    return "prepare-download -> %s" % data["url"]


@check("resolve+search", full=True)
def check_resolve_and_search():
    """End-to-end: zimuku ladder, douban bridge to SubHD, both sites' search."""
    query = WorkQuery(title=WORK_QUERY, year="2010")
    work = resolve_work(query, log=lambda msg: None)
    assert work, "resolution failed (zimuku empty or failing)"
    assert "zimuku" in work.anchors, "no zimuku anchor on the picked work"
    results = search_all(query, work, log=lambda msg: None)
    assert results, "search returned nothing"
    providers = {s.tags.provider for s in results}
    return "work [%s] from %s, %d subtitles" % (
        "+".join(work.anchors), sorted(providers), len(results))


@check("subhd/download", full=True)
def check_subhd_download():
    provider = SubhdProvider()
    works = [w for w in provider.find_works(WorkQuery(title=WORK_QUERY))
             if "Inception" in w.title]
    assert works, "work search returned nothing"
    results = provider.search(WorkQuery(title=WORK_QUERY), works[0])
    assert results, "search returned nothing"
    with tempfile.TemporaryDirectory() as dest:
        result = provider.download(results[0].link, dest)
        assert result.status == "ok" and result.files, \
            "download failed (prepare-download -> temp page -> /api/sub/down broken)"
        return "extracted %d files, e.g. %s" % (len(result.files), result.files[0])


@check("zimuku/download", full=True)
def check_zimuku_download():
    provider = ZimukuProvider()
    works = provider.find_works(WorkQuery(title=WORK_QUERY))
    assert works, "work search returned nothing"
    results = provider.search(WorkQuery(title=WORK_QUERY), works[0])
    assert results, "search returned nothing"
    with tempfile.TemporaryDirectory() as dest:
        result = provider.download(results[0].link, dest)
        assert result.status == "ok" and result.files, "download failed"
        return "extracted %d files, e.g. %s" % (len(result.files), result.files[0])


def run(full=False, only=None):
    if only and not any(name == only for name, _, _ in CHECKS):
        print("unknown check: %s" % only)
        print("available checks: %s" % ", ".join(name for name, _, _ in CHECKS))
        return 1

    rows, failures = [], 0
    for name, fn, full_only in CHECKS:
        if only:
            # an explicitly named check runs even in full-only mode
            if only != name:
                continue
        elif full_only and not full:
            continue
        start = time.time()
        try:
            detail = fn()
            rows.append((name, True, "%.1fs  %s" % (time.time() - start, detail)))
        except Exception as e:
            failures += 1
            rows.append((name, False, "%.1fs  %s: %s" % (time.time() - start, type(e).__name__, e)))

    mode = "full" if full else "light"
    print("\nExternal services health check (%s)  %s" % (mode, time.strftime("%Y-%m-%d %H:%M:%S")))
    print("-" * 72)
    width = max([len(n) for n, _, _ in rows] + [10])
    for name, ok, detail in rows:
        print("[%-4s] %-*s  %s" % ("OK" if ok else "FAIL", width, name, detail))
    print("-" * 72)
    print("%d/%d passed" % (len(rows) - failures, len(rows)))
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="External subtitle services health check")
    parser.add_argument("--full", action="store_true", help="include real subtitle downloads")
    parser.add_argument("--only", help="run a single named check (e.g. subhd/download-api)")
    args = parser.parse_args()
    sys.exit(min(run(full=args.full, only=args.only), 1))


# ---- pytest entry points ----

def test_external_services_light():
    assert run(full=False) == 0


def test_external_services_full():
    if os.environ.get("CHINESESUB_FULL") != "1":
        import pytest
        pytest.skip("set CHINESESUB_FULL=1 to enable full download checks")
    assert run(full=True) == 0
