# -*- coding: utf-8 -*-
"""Live tests for the SubHD provider: direct /d/{douban id} search, download."""
import os
import sys
import tempfile

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
lib_dir = os.path.join(base_dir, "resources", "lib")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)

from core.models import Work, WorkQuery, build_label
from core.subhd import SubhdProvider

# Friends S1's Douban subject id: SubHD serves work pages under it directly
FRIENDS_S1_DOUBAN = "1393859"


def test_subhd_search_and_download():
    log = lambda msg: print(f"  [subhd] {msg}")
    provider = SubhdProvider(log=log)

    print("\n=== SubHD direct /d/{douban id}: Friends S1 ===")
    query = WorkQuery(title="老友记 Friends", season="1", is_tv=True)
    work = Work(title="老友记 第一季 Friends", season="1",
                anchors={"subhd": [f"/d/{FRIENDS_S1_DOUBAN}"]})
    results = provider.search(query, work)
    assert results, "SubHD direct douban-id page returned no subtitles."
    print(f"Total subtitles found: {len(results)}")
    for i, s in enumerate(results[:5]):
        print(f"[{i:2}] {build_label(s.tags, filename=s.filename)}")

    print("\n=== Downloading first subtitle ===")
    with tempfile.TemporaryDirectory() as dest:
        result = provider.download(results[0].link, dest)
        print(f"status={result.status} files={result.files}")
        assert result.status == "ok" and result.files, "SubHD download failed."
        assert all(os.path.exists(p) for p in result.paths)
