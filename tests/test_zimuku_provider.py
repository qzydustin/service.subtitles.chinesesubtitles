# -*- coding: utf-8 -*-
"""Zimuku provider tests: live work discovery, TV search, download,
plus offline page-parsing regressions."""
import os
import sys
import tempfile

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
lib_dir = os.path.join(base_dir, "resources", "lib")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)

from core.models import WorkQuery, build_label
from core.zimuku import ZimukuProvider


def test_zimuku_work_page_skips_linkless_rows(monkeypatch):
    # offline: one linkless row (ad/placeholder) must not sink the page
    html = """
    <div class="subs box clearfix"><table><tbody>
      <tr><td>placeholder without a link</td></tr>
      <tr><td><a href="/detail/1.html">Show.S01E01.srt</a></td></tr>
    </tbody></table></div>
    """
    provider = ZimukuProvider()
    monkeypatch.setattr(provider, "_get", lambda url, referer=None: html.encode())
    _, subs = provider.work_page(WorkQuery(title="x"), "https://zimuku.org/subs/1.html")
    assert [s.filename for s in subs] == ["Show.S01E01.srt"]


def test_zimuku_find_works():
    provider = ZimukuProvider(log=lambda msg: print(f"  [zimuku] {msg}"))

    print("\n=== Zimuku find_works: 绝命毒师 (pagination must reach all seasons) ===")
    works = provider.find_works(WorkQuery(title="绝命毒师"))
    assert works, "Zimuku work search returned no results."
    seasons = {w.season for w in works if w.season}
    assert {"1", "2", "3", "4", "5"} <= seasons, \
        f"Missing seasons, got {sorted(seasons)} among {len(works)} works"
    print(f"Total works: {len(works)}, seasons found: {sorted(seasons)}")
    for i, w in enumerate(works[:5], start=1):
        print(f"{i}. {w.title} | season={w.season!r} year={w.year!r} | {w.anchors['zimuku'][0]}")


def test_zimuku_work_page():
    provider = ZimukuProvider(log=lambda msg: print(f"  [zimuku] {msg}"))

    print("\n=== Zimuku work page: 老友记 第一季 (douban id + subtitles in one fetch) ===")
    works = provider.find_works(WorkQuery(title="老友记 Friends"))
    s1 = next(w for w in works if w.season == "1")
    query = WorkQuery(title="老友记 Friends", season="1", is_tv=True)
    douban, subs = provider.work_page(query, s1.anchors["zimuku"][0])
    print(f"work: {s1.title} | douban id: {douban} | subtitles: {len(subs)}")
    assert douban == "1393859", f"unexpected douban id: {douban}"
    assert subs, "work page yielded no subtitles"


def test_zimuku_search_and_download():
    log = lambda msg: print(f"  [zimuku] {msg}")
    provider = ZimukuProvider(log=log)

    print("\n=== Zimuku search: 电锯人 S01E02 ===")
    query = WorkQuery(title="电锯人", season="1", episode="2", is_tv=True, year="2022")
    found = provider.find_works(query)
    # single-season shows are often listed without an explicit season marker
    works = [w for w in found if w.season == "1"] or \
            [w for w in found if "电锯人" in w.title]
    assert works, "No matching work found."
    print(f"Work: {works[0].title} | anchor={works[0].anchors['zimuku']}")

    results = provider.search(query, works[0])
    assert results, "Zimuku search returned no subtitles."
    print(f"Total subtitles found: {len(results)}")
    for i, s in enumerate(results[:5]):
        print(f"[{i:2}] {build_label(s.tags, filename=s.filename)}")

    print("\n=== Downloading first subtitle ===")
    with tempfile.TemporaryDirectory() as dest:
        result = provider.download(results[0].link, dest)
        print(f"status={result.status} files={result.files}")
        assert result.status == "ok" and result.files, "Zimuku download failed."
        assert all(os.path.exists(p) for p in result.paths)
