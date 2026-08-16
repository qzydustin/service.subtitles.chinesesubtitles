# -*- coding: utf-8 -*-
"""Offline unit tests for core: matcher, models, filter, service orchestration, http helpers."""
import os
import sys

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
lib_dir = os.path.join(base_dir, "resources", "lib")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)

from core import service
from core.archive import shorten_names
from core.filter import apply_filters
from core.http import filename_from_headers
from core.matcher import parse_filename, parse_meta, works_match
from core.models import Subtitle, Tags, Work, WorkQuery, build_label, language_meta


def make_sub(langs=(), fmts=("srt",), sources=(), bilingual=False):
    return Subtitle("n", "l", Tags(lang=list(langs), fmt=list(fmts),
                                    source=list(sources), bilingual=bilingual))


ALL_TRUE = {
    "src_official": True, "src_reprint": True, "src_original": True,
    "src_ai": True, "src_machine": True,
    "lang_chs": True, "lang_cht": True, "lang_eng": True,
    "fmt_ass": True, "fmt_srt": True, "fmt_ssa": True, "fmt_sub": True,
    "fmt_sup": True, "fmt_vtt": True,
}


# ---- matcher ----

def test_match_links_word_order():
    assert works_match("绝命毒师电影：续命之徒", "续命之徒：绝命毒师电影")


def test_match_season_must_be_equal():
    assert not works_match("绝命毒师 第一季 Breaking Bad", "绝命毒师 第二季 Breaking Bad")
    # a seasonless title never connects to a seasoned one
    assert not works_match("绝命毒师 Breaking Bad", "绝命毒师 第二季 Breaking Bad")


def test_match_year_conflict_blocks():
    assert not works_match("绝命毒师 第二季 Breaking Bad (2009)",
                           "绝命毒师 第二季 Breaking Bad (2010)")


def test_match_one_sided_year_ok():
    assert works_match("绝命毒师 第二季 Breaking Bad (2009)",
                       "绝命毒师 第二季 Breaking Bad")


def test_match_chinese_numeral_season():
    tokens, season, year = parse_meta("绝命毒师 第二季 Breaking Bad")
    assert season == "2" and year == "" and tokens == {"绝命毒师", "breaking", "bad"}
    assert works_match("绝命毒师 第二季 Breaking Bad", "绝命毒师 Season 2 Breaking Bad")


def test_match_complex_season_treated_as_none():
    # Chinese-numeral seasons above ten don't parse; they count as no season
    _, season, _ = parse_meta("神秘博士 第十一季")
    assert season == ""


def test_match_normalizes_punctuation_and_case():
    assert works_match("Breaking  Bad  (2009)", "breaking.bad")
    assert works_match("Show：名侦探柯南", "名侦探柯南 show")


def test_match_noise_stays_apart():
    # Leatherface rides along in Chainsaw-Man searches on Zimuku; it must not merge
    assert not works_match("人皮脸 Leatherface", "电锯人")
    assert not works_match("", "")


def test_match_english_season_form():
    assert works_match("Friends Season 2", "老友记 第二季 Friends") is False  # extra token
    assert works_match("Friends Season 2", "Friends 第二季")


# ---- aggregation ----

def subhd_work(title, season="", year="", href="/d/1"):
    return Work(title=title, season=season, year=year, anchors={"subhd": [href]})


def zimuku_work(title, season="", year="", url="https://zimuku.org/subs/1.html"):
    return Work(title=title, season=season, year=year, anchors={"zimuku": [url]})


def test_aggregate_merges_unique_match():
    rows = service.aggregate(
        [subhd_work("绝命毒师 第二季 Breaking Bad", season="2")],
        [zimuku_work("绝命毒师  第二季 Breaking Bad  (2009)", season="2", year="2009")])
    assert len(rows) == 1
    row = rows[0]
    assert set(row.anchors) == {"subhd", "zimuku"}
    assert row.year == "2009"  # adopted from the zimuku side


def test_aggregate_zero_match_keeps_own_rows():
    rows = service.aggregate(
        [subhd_work("盗梦空间 Inception", href="/d/1")],
        [zimuku_work("人皮脸 Leatherface", year="2017")])
    assert len(rows) == 2
    assert all(len(r.anchors) == 1 for r in rows)


def test_aggregate_ambiguous_match_never_merges():
    # two same-named SubHD works: linking the zimuku row to either would guess
    rows = service.aggregate(
        [subhd_work("盗梦空间 Inception", href="/d/1"),
         subhd_work("Inception 盗梦空间", href="/d/2")],
        [zimuku_work("盗梦空间 Inception", year="2010")])
    assert len(rows) == 3
    assert all(len(r.anchors) == 1 for r in rows)


def test_aggregate_duplicate_pages_share_one_row():
    # Zimuku may list the same work twice (with and without the year); both
    # pages must stay reachable on a single merged row
    rows = service.aggregate(
        [subhd_work("复仇者联盟", href="/d/av")],
        [zimuku_work("复仇者联盟 (2012)", year="2012", url="u1"),
         zimuku_work("复仇者联盟", url="u2")])
    assert len(rows) == 1
    assert rows[0].anchors == {"subhd": ["/d/av"], "zimuku": ["u1", "u2"]}
    assert rows[0].year == "2012"


def test_aggregate_one_site_empty_still_lists():
    rows = service.aggregate([subhd_work("绝命毒师 Breaking Bad", href="/d/1")], [])
    assert len(rows) == 1 and "subhd" in rows[0].anchors
    rows = service.aggregate([], [zimuku_work("绝命毒师 Breaking Bad")])
    assert len(rows) == 1 and "zimuku" in rows[0].anchors


def test_order_works_season_first_then_year():
    query = WorkQuery(title="绝命毒师", season="5", year="2012")
    rows = [
        zimuku_work("绝命毒师 第一季 Breaking Bad", season="1", year="2008", url="u1"),
        subhd_work("绝命毒师 第五季 Breaking Bad", season="5", href="/d/5"),
        subhd_work("绝命毒师 第二季 Breaking Bad", season="2", href="/d/2"),
        zimuku_work("绝命毒师 第五季 Breaking Bad", season="5", year="2012", url="u5"),
    ]
    ordered = service.order_works(rows, query)
    assert ordered[0].season == "5" and ordered[1].season == "5"
    assert ordered[0].year == "2012"  # among season hits, closest year first
    # past the season hits, year closeness ranks before site order
    assert [r.season for r in ordered[2:]] == ["1", "2"]


# ---- service orchestration ----

class FakeProvider:
    name = "fake"

    def __init__(self, log=None, backend=None):
        self.log = log

    def find_works(self, query):
        return [subhd_work("绝命毒师 Breaking Bad")]

    def search(self, query, work):
        return [Subtitle("a.srt", "http://a", Tags(lang=["chs"]))]

    def download(self, link, dest):
        from core.models import DownloadResult
        return DownloadResult("ok", [link], [link], [dest + "/" + link])


class RaisingProvider(FakeProvider):
    def find_works(self, query):
        raise RuntimeError("site down")

    def search(self, query, work):
        raise RuntimeError("site down")


def patch_providers(monkeypatch, providers):
    monkeypatch.setattr(service, "PROVIDERS", providers)


def test_resolve_work_isolated_when_one_site_fails(monkeypatch):
    class SubhdSide(FakeProvider):
        def find_works(self, query):
            return [subhd_work("绝命毒师 Breaking Bad")]

    class ZimukuSide(FakeProvider):
        def find_works(self, query):
            return [zimuku_work("绝命毒师 Breaking Bad")]

    patch_providers(monkeypatch, {"subhd": SubhdSide, "zimuku": RaisingProvider})
    picked = service.resolve_work(WorkQuery(title="绝命毒师"), log=lambda msg: None)
    assert picked is not None and "subhd" in picked.anchors

    patch_providers(monkeypatch, {"subhd": RaisingProvider, "zimuku": ZimukuSide})
    picked = service.resolve_work(WorkQuery(title="绝命毒师"), log=lambda msg: None)
    assert picked is not None and "zimuku" in picked.anchors


def test_resolve_work_single_row_skips_picker(monkeypatch):
    calls = []
    patch_providers(monkeypatch, {"subhd": FakeProvider, "zimuku": FakeProvider})
    # both sites agree -> one merged row -> choose never invoked
    picked = service.resolve_work(WorkQuery(title="x"),
                                  choose=lambda t, o: calls.append(o) or None)
    assert picked is not None and not calls


def test_resolve_work_picker_paths(monkeypatch):
    class TwoWorks(FakeProvider):
        def find_works(self, query):
            return [subhd_work("A", href="/d/1"), subhd_work("B", href="/d/2")]

    patch_providers(monkeypatch, {"subhd": TwoWorks, "zimuku": RaisingProvider})
    query = WorkQuery(title="x")

    # headless: first row wins
    assert service.resolve_work(query).title == "A"
    # picker selects the second row
    picked = service.resolve_work(query, choose=lambda t, o: 1)
    assert picked.title == "B"
    # picker cancelled / out of range
    assert service.resolve_work(query, choose=lambda t, o: None) is None
    assert service.resolve_work(query, choose=lambda t, o: 99) is None


def test_resolve_work_nothing_found(monkeypatch):
    class Empty(FakeProvider):
        def find_works(self, query):
            return []

    patch_providers(monkeypatch, {"subhd": Empty, "zimuku": Empty})
    assert service.resolve_work(WorkQuery(title="不存在")) is None


def test_resolve_work_alt_titles_ladder(monkeypatch):
    class PickyProvider(FakeProvider):
        def find_works(self, query):
            return [subhd_work("Fallback Hit")] if query.title == "alt" else []

    patch_providers(monkeypatch, {"subhd": PickyProvider, "zimuku": RaisingProvider})
    picked = service.resolve_work(
        WorkQuery(title="wrong", alt_titles=["nope", "alt"]),
        log=lambda msg: None)
    assert picked is not None and picked.title == "Fallback Hit"


def test_search_all_anchors_and_isolation(monkeypatch):
    query = WorkQuery(title="绝命毒师", season="2", episode="5", is_tv=True)

    # only sites whose anchor the work carries are searched
    patch_providers(monkeypatch, {"subhd": FakeProvider, "zimuku": RaisingProvider})
    work = Work(title="绝命毒师 第二季", anchors={"subhd": ["/d/1"]})
    subs = service.search_all(query, work, log=lambda msg: None)
    assert len(subs) == 1 and subs[0].tags.provider == "subhd"

    # a raising site degrades to nothing, the healthy one survives
    work = Work(title="绝命毒师 第二季", anchors={"subhd": ["/d/1"], "zimuku": ["u"]})
    subs = service.search_all(query, work, log=lambda msg: None)
    assert len(subs) == 1 and subs[0].tags.provider == "subhd"


def test_download_dispatch(monkeypatch):
    patch_providers(monkeypatch, {"subhd": FakeProvider})
    result = service.download("x.srt", "subhd", dest="/tmp/fake")
    assert result.status == "ok" and result.files == ["x.srt"]
    # unknown provider falls back to subhd
    result = service.download("y.srt", "nope", dest="/tmp/fake")
    assert result.files == ["y.srt"]


# ---- models ----

def test_build_label():
    tags = Tags(lang=["chs", "eng"], fmt=["ass"], source=["official"],
                production="电影", fansub="YYeTs")
    assert build_label(tags, filename="name.ass") == "[电影][简英][官方][ASS][YYeTs] name.ass"


def test_build_label_collection():
    tags = Tags(collection=True)
    assert build_label(tags) == "[合集]"


def test_language_meta():
    assert language_meta(Tags(lang=["eng"])) == ("English", "en")
    assert language_meta(Tags(lang=["chs", "eng"])) == ("Chinese", "zh")
    assert language_meta(Tags()) == ("Chinese", "zh")


# ---- filename parsing ----

def test_parse_filename_scene_tv():
    out = parse_filename("Show.Name.S02E05.720p.x264-GRP.mkv")
    assert out == {"title": "Show Name", "year": "", "season": "2", "episode": "5"}


def test_parse_filename_movie_year():
    out = parse_filename("Movie.Name.2010.1080p.BluRay.mkv")
    assert out == {"title": "Movie Name", "year": "2010", "season": "", "episode": ""}


def test_parse_filename_chinese_season_episode():
    out = parse_filename("某剧.第二季.第05集.mkv")
    assert out == {"title": "某剧", "year": "", "season": "2", "episode": "5"}


def test_parse_filename_lowercase_marker():
    out = parse_filename("show.name.s1e2.mkv")
    assert out["title"] == "show name" and out["season"] == "1" and out["episode"] == "2"


def test_parse_filename_strips_release_tags_best_effort():
    out = parse_filename("Some.Show.2160p.HDTV.x265")
    assert out["title"] == "Some Show"
    # files without a year or episode marker keep some tag residue ("DL");
    # acceptable for a fallback path, both sites' search tolerates it
    assert parse_filename("Some.Show.WEB-DL.2160p")["title"] == "Some Show DL"


def test_parse_filename_no_markers():
    out = parse_filename("plainname")
    assert out == {"title": "plainname", "year": "", "season": "", "episode": ""}
    assert parse_filename("")["title"] == ""


# ---- http helpers ----

def test_filename_from_headers():
    assert filename_from_headers('attachment; filename="a.srt"') == "a.srt"
    assert filename_from_headers("attachment; filename*=UTF-8''%E4%B8%AD.srt") == "中.srt"
    assert filename_from_headers(None, url="http://x/y/sub.zip") == "sub.zip"
    assert filename_from_headers(None) is None
    assert filename_from_headers(None, url="http://x/", default="f.bin") == "f.bin"


# ---- archive helpers ----

def test_shorten_names():
    names = ["dir.a.1.ass", "dir.a.2.ass"]
    assert shorten_names(names) == ["1.ass", "2.ass"]
    assert shorten_names(["only.ass"]) == ["only.ass"]
    assert shorten_names([]) == []


# ---- filter ----

def test_filter_bilingual_is_hard():
    subs = [make_sub(), make_sub(bilingual=True)]
    kept = apply_filters(subs, {**ALL_TRUE, "bilingual": True})
    assert [s.tags.bilingual for s in kept] == [True]


def test_filter_language():
    subs = [make_sub(langs=["chs"]), make_sub(langs=["cht"])]
    kept = apply_filters(subs, {**ALL_TRUE, "lang_chs": True, "lang_cht": False})
    assert [s.tags.lang for s in kept] == [["chs"]]


def test_filter_source():
    subs = [make_sub(sources=["official"]), make_sub(sources=["machine"])]
    kept = apply_filters(subs, {**ALL_TRUE, "src_machine": False})
    assert [s.tags.source for s in kept] == [["official"]]


def test_filter_format():
    subs = [make_sub(fmts=["ass"]), make_sub(fmts=["srt"])]
    kept = apply_filters(subs, {**ALL_TRUE, "fmt_srt": True, "fmt_ass": False})
    assert [s.tags.fmt for s in kept] == [["srt"]]


def test_filter_missing_tags_pass():
    # unknown/absent tag lists are never hidden by their filter
    bare = make_sub(fmts=[], sources=[], langs=[])
    assert apply_filters([bare], {**ALL_TRUE, "bilingual": True}) == []  # bilingual still hard
    assert apply_filters([bare], ALL_TRUE) == [bare]


def test_filter_sorts_by_language_then_source():
    subs = [
        make_sub(langs=["cht"]),                                   # tier 3
        make_sub(langs=["chs"], sources=["machine"]),              # tier 1
        make_sub(langs=["chs"], bilingual=True, sources=["ai"]),   # tier 0, src 3
        make_sub(langs=["chs"], bilingual=True, sources=["official"]),  # tier 0, src 0
        make_sub(langs=["eng"]),                                   # tier 4
    ]
    kept = apply_filters(subs, ALL_TRUE)
    assert [(s.tags.lang, s.tags.source) for s in kept] == [
        (["chs"], ["official"]), (["chs"], ["ai"]), (["chs"], ["machine"]),
        (["cht"], []), (["eng"], []),
    ]
