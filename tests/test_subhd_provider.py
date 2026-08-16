# -*- coding: utf-8 -*-
"""Live tests for the SubHD provider: work discovery, TV search, download."""
import os
import sys
import tempfile

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
lib_dir = os.path.join(base_dir, "resources", "lib")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)

from core.models import WorkQuery, build_label
from core.subhd import SubhdProvider


def test_subhd_find_works():
    provider = SubhdProvider(log=lambda msg: print(f"  [subhd] {msg}"))

    print("\n=== SubHD find_works: 盗梦空间 ===")
    works = provider.find_works(WorkQuery(title="盗梦空间"))
    assert works, "SubHD work search returned no results."
    assert any("Inception" in w.title for w in works), \
        f"No Inception work among: {[w.title for w in works]}"
    print(f"Total works: {len(works)}")
    for i, w in enumerate(works[:5], start=1):
        print(f"{i}. {w.title} | season={w.season!r} | anchor={w.anchors['subhd'][0]}")

    print("\n=== SubHD find_works: 绝命毒师 (pagination must reach all seasons) ===")
    works = provider.find_works(WorkQuery(title="绝命毒师"))
    seasons = {w.season for w in works if w.season}
    assert {"1", "2", "3", "4", "5"} <= seasons, \
        f"Missing seasons, got {sorted(seasons)} among {len(works)} works"
    print(f"Total works: {len(works)}, seasons found: {sorted(seasons)}")


def test_subhd_search_and_download():
    log = lambda msg: print(f"  [subhd] {msg}")
    provider = SubhdProvider(log=log)

    print("\n=== SubHD search: Breaking Bad S02E05 ===")
    query = WorkQuery(title="绝命毒师", season="2", episode="5", is_tv=True)
    works = [w for w in provider.find_works(query) if w.season == "2"]
    assert works, "Season 2 work not found."
    print(f"Work: {works[0].title} | anchor={works[0].anchors['subhd'][0]}")

    results = provider.search(query, works[0])
    assert results, "SubHD search returned no subtitles."
    print(f"Total subtitles found: {len(results)}")
    for i, s in enumerate(results[:5]):
        print(f"[{i:2}] {build_label(s.tags, filename=s.filename)}")

    print("\n=== Downloading first subtitle ===")
    with tempfile.TemporaryDirectory() as dest:
        result = provider.download(results[0].link, dest)
        print(f"status={result.status} files={result.files}")
        assert result.status == "ok" and result.files, "SubHD download failed."
        assert all(os.path.exists(p) for p in result.paths)
