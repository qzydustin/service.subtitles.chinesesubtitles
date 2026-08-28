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
from core.matcher import parse_filename, parse_meta, season_number
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

def test_parse_meta_season_and_year():
    season, year = parse_meta("绝命毒师 第二季 Breaking Bad")
    assert season == "2" and year == ""


def test_parse_meta_compound_numeral_season():
    # Chinese-numeral compounds through 九十九 parse like their digit forms
    season, _ = parse_meta("神秘博士 第十一季")
    assert season == "11"


def test_season_number_compounds():
    assert season_number("2") == 2 and season_number("二") == 2
    assert season_number("十") == 10 and season_number("十一") == 11
    assert season_number("二十") == 20 and season_number("二十九") == 29
    assert season_number("九十九") == 99
    # garbage numerals stay unparsable, not misread as a nearby value
    assert season_number("十x") == 0 and season_number("x十") == 0
    assert season_number("百") == 0 and season_number("十一一") == 0


def test_parse_meta_year_bracket():
    season, year = parse_meta("老友记 第十季 Friends  (2003)")
    assert season == "10" and year == "2003"


def subhd_work(title, season="", year="", href="/d/1"):
    return Work(title=title, season=season, year=year, anchors={"subhd": [href]})


def zimuku_work(title, season="", year="", url="https://zimuku.org/subs/1.html"):
    return Work(title=title, season=season, year=year, anchors={"zimuku": [url]})


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
        return [zimuku_work("绝命毒师 Breaking Bad")]

    def work_page(self, query, url):
        return "1393859", []

    def search(self, query, work):
        return [Subtitle("a.srt", "http://a", Tags(lang=["chs"]))]

    def download(self, link, dest):
        from core.models import DownloadResult
        return DownloadResult("ok", files=[link], display_names=[link],
                              paths=[dest + "/" + link])


class RaisingProvider(FakeProvider):
    def find_works(self, query):
        raise RuntimeError("site down")

    def work_page(self, query, url):
        raise RuntimeError("site down")

    def search(self, query, work):
        raise RuntimeError("site down")


def patch_providers(monkeypatch, providers):
    monkeypatch.setattr(service, "PROVIDERS", providers)


def test_resolve_work_bridges_subhd_by_douban_id(monkeypatch):
    patch_providers(monkeypatch, {"zimuku": FakeProvider, "subhd": RaisingProvider})
    picked = service.resolve_work(WorkQuery(title="绝命毒师"), log=lambda msg: None)
    assert picked.anchors == {"zimuku": ["https://zimuku.org/subs/1.html"],
                              "subhd": ["/d/1393859"]}


def test_resolve_work_survives_a_broken_bridge(monkeypatch):
    class NoDouban(FakeProvider):
        def work_page(self, query, url):
            return "", []

    class Gone(FakeProvider):
        def work_page(self, query, url):
            raise RuntimeError("page gone")

    for side in (NoDouban, Gone):
        patch_providers(monkeypatch, {"zimuku": side, "subhd": RaisingProvider})
        picked = service.resolve_work(WorkQuery(title="x"), log=lambda msg: None)
        assert "subhd" not in picked.anchors and "zimuku" in picked.anchors


def test_resolve_work_preloads_zimuku_subtitles(monkeypatch):
    sub = Subtitle("pre.srt", "http://pre", Tags(lang=["chs"]))

    class Preload(FakeProvider):
        def work_page(self, query, url):
            return "1393859", [sub]

        def search(self, query, work):
            raise AssertionError("zimuku re-fetched despite the preload")

    patch_providers(monkeypatch, {"zimuku": Preload, "subhd": FakeProvider})
    work = service.resolve_work(WorkQuery(title="x"), log=lambda m: None)
    subs = service.search_all(WorkQuery(title="x"), work, log=lambda m: None)
    mine = [s for s in subs if s.tags.provider == "zimuku"]
    assert mine == [sub]  # the preloaded object itself, no re-fetch


def test_resolve_work_single_row_skips_picker(monkeypatch):
    calls = []
    patch_providers(monkeypatch, {"zimuku": FakeProvider, "subhd": FakeProvider})
    picked = service.resolve_work(WorkQuery(title="x"),
                                  choose=lambda t, o: calls.append(o) or None,
                                  log=lambda msg: None)
    assert picked is not None and not calls


def test_resolve_work_year_attempt_comes_first(monkeypatch):
    class ByYear(FakeProvider):
        seen = []

        def find_works(self, query):
            ByYear.seen.append(query.title)
            return [zimuku_work("悲惨世界 Les Misérables (2012)", year="2012")] \
                if query.title.endswith("2012") else []

    patch_providers(monkeypatch, {"zimuku": ByYear, "subhd": FakeProvider})
    picked = service.resolve_work(
        WorkQuery(title="悲惨世界 Les Misérables", year="2012"), log=lambda msg: None)
    assert ByYear.seen[0] == "悲惨世界 Les Misérables 2012"
    assert picked.year == "2012"


def test_resolve_work_season_filters_rows(monkeypatch):
    class Seasons(FakeProvider):
        def find_works(self, query):
            return [zimuku_work("老友记 第一季 Friends", season="1", year="1994"),
                    zimuku_work("老友记 第十季 Friends", season="10", year="2003"),
                    zimuku_work("老友记 Friends 合集", season="")]

    offered = []
    patch_providers(monkeypatch, {"zimuku": Seasons, "subhd": FakeProvider})
    picked = service.resolve_work(
        WorkQuery(title="老友记 Friends", season="10", is_tv=True),
        choose=lambda t, o: offered.append(o) or 0, log=lambda msg: None)
    # other seasons dropped, the season-less pack kept; exact season first
    assert len(offered[0]) == 2
    assert picked.season == "10"


def test_resolve_work_picker_paths(monkeypatch):
    class TwoWorks(FakeProvider):
        def find_works(self, query):
            return [zimuku_work("A", url="u1"), zimuku_work("B", url="u2")]

    patch_providers(monkeypatch, {"zimuku": TwoWorks, "subhd": FakeProvider})
    query = WorkQuery(title="x")

    # headless: first row wins
    assert service.resolve_work(query, log=lambda m: None).title == "A"
    # picker selects the second row
    picked = service.resolve_work(query, choose=lambda t, o: 1, log=lambda m: None)
    assert picked.title == "B"
    # picker cancelled / out of range
    assert service.resolve_work(query, choose=lambda t, o: None, log=lambda m: None) is None
    assert service.resolve_work(query, choose=lambda t, o: 99, log=lambda m: None) is None


def test_resolve_work_nothing_found(monkeypatch):
    class Empty(FakeProvider):
        def find_works(self, query):
            return []

    patch_providers(monkeypatch, {"zimuku": Empty})
    assert service.resolve_work(WorkQuery(title="不存在"), log=lambda m: None) is None


def test_resolve_work_alt_titles_ladder(monkeypatch):
    class PickyProvider(FakeProvider):
        def find_works(self, query):
            return [zimuku_work("Fallback Hit")] if query.title == "alt" else []

    patch_providers(monkeypatch, {"zimuku": PickyProvider, "subhd": FakeProvider})
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
    # dot-free junk spellings all strip, longest tag first (WEBDL goes whole,
    # HDR10 is not half-stripped by HDR)
    assert parse_filename("Show.10bit.HDR10.WEBDL.DDP51.x264")["title"] == "Show"
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


# ---- autosave ----

def test_episode_marker_variants():
    from core.matcher import episode_marker
    assert episode_marker("Show.S02E05.720p") == (2, 5)
    assert episode_marker("Show.S02.E05.720p") == (2, 5)  # dot-separated form
    assert episode_marker("第12集") == (None, 12)
    assert episode_marker("someone.EP3.x264") == (None, 3)
    assert episode_marker("Movie.2010.1080p") == (None, None)


def test_rename_map_single_subtitle():
    from core.autosave import rename_map
    assert rename_map(["pack.ass"], "Movie.2010", ["other.mkv"]) == {"pack.ass": "Movie.2010"}
    # a language tag survives even a single rename, so a later twin download
    # cannot overwrite this file
    assert rename_map(["pack.chs.ass"], "Movie.2010", []) == {"pack.chs.ass": "Movie.2010.chs"}


def test_rename_map_pack_matches_sibling_episodes():
    from core.autosave import rename_map
    subs = ["Show.S01E01.chs.ass", "Show.S01E02.chs.ass", "Show.S01E03.chs.ass"]
    siblings = ["Show.S01E01.720p", "Show.S01E02.720p", "Show.S01E03.720p", "notes.txt"]
    mapping = rename_map(subs, "Show.S01E02.720p", siblings)
    assert mapping == {
        "Show.S01E01.chs.ass": "Show.S01E01.720p.chs",
        "Show.S01E02.chs.ass": "Show.S01E02.720p.chs",
        "Show.S01E03.chs.ass": "Show.S01E03.720p.chs",
    }


def test_rename_map_twins_keep_language_tags():
    from core.autosave import rename_map
    subs = ["Show.S01E02.chs.ass", "Show.S01E02.cht.ass"]
    assert rename_map(subs, "Show.S01E02.720p", []) == {
        "Show.S01E02.chs.ass": "Show.S01E02.720p.chs",
        "Show.S01E02.cht.ass": "Show.S01E02.720p.cht",
    }


def test_rename_map_unmarked_pack_entry_skipped():
    from core.autosave import rename_map
    mapping = rename_map(["readme.txt.srt", "Show.S01E02.chs.ass"],
                         "Show.S01E02.720p", [])
    assert mapping == {"Show.S01E02.chs.ass": "Show.S01E02.720p.chs"}


def test_rename_map_season_disambiguation():
    from core.autosave import rename_map
    subs = ["t.S01E05.ass", "t.S02E05.ass"]
    siblings = ["Show.S01E05.mkv", "Show.S02E05.mkv"]
    mapping = rename_map(subs, "Show.S02E05.mkv", siblings, season=2)
    assert mapping["t.S01E05.ass"] == "Show.S01E05.mkv"
    assert mapping["t.S02E05.ass"] == "Show.S02E05.mkv"


def test_rename_map_movie_twins():
    from core.autosave import rename_map
    subs = ["Inception.chs.srt", "Inception.cht.srt"]
    assert rename_map(subs, "Inception.2010", []) == {
        "Inception.chs.srt": "Inception.2010.chs",
        "Inception.cht.srt": "Inception.2010.cht",
    }


def test_playback_pick_prefers_enabled_language():
    from core.autosave import playback_pick, rename_map
    subs = ["Show.S01E02.chs.ass", "Show.S01E02.cht.ass"]
    mapping = rename_map(subs, "Show.S01E02.720p", [])
    assert playback_pick(mapping, "Show.S01E02.720p") == "Show.S01E02.chs.ass"
    assert playback_pick(mapping, "Show.S01E02.720p", preferred=("cht",)) == "Show.S01E02.cht.ass"


def test_playback_pick_current_episode_and_no_match():
    from core.autosave import playback_pick, rename_map
    subs = ["Show.S01E01.ass", "Show.S01E02.ass", "Show.S01E03.ass"]
    mapping = rename_map(subs, "Show.S01E02.720p", ["Show.S01E01.mkv", "Show.S01E03.mkv"])
    assert playback_pick(mapping, "Show.S01E02.720p") == "Show.S01E02.ass"
    # nothing maps to the playing video -> caller falls back to the picker
    assert playback_pick({}, "Show.S01E02.720p") == ""
    assert playback_pick(mapping, "Different.Video") == ""


def test_playback_pick_prefers_bilingual_twin():
    from core.autosave import playback_pick, rename_map
    # mono file first in the archive: bilingual must still win
    subs = ["Show.S04E01.chs.srt", "Show.S04E01.eng.srt", "Show.S04E01.chs&eng.srt"]
    mapping = rename_map(subs, "Show.S04E01.1080p", [])
    assert playback_pick(mapping, "Show.S04E01.1080p") == "Show.S04E01.chs&eng.srt"
    # Chinese-styled tags too
    subs = ["Movie.简体.srt", "Movie.简英双语.srt", "Movie.英文.srt"]
    mapping = rename_map(subs, "Movie.2010", [])
    assert playback_pick(mapping, "Movie.2010") == "Movie.简英双语.srt"
    # no language-code hint at all: a bilingual mark still beats position
    subs = ["Movie.英文.srt", "Movie.中英.srt"]
    mapping = rename_map(subs, "Movie.2010", [])
    assert playback_pick(mapping, "Movie.2010", preferred=("chs",)) == "Movie.中英.srt"


def test_playback_candidates_best_first():
    from core.autosave import playback_candidates, rename_map
    subs = ["Movie.eng.srt", "Movie.chs.srt", "Movie.chs&eng.srt", "Movie.cht.srt"]
    mapping = rename_map(subs, "Movie.2010", [])
    assert playback_candidates(mapping, "Movie.2010") == [
        "Movie.chs&eng.srt", "Movie.chs.srt", "Movie.cht.srt", "Movie.eng.srt"]
    assert playback_candidates(mapping, "Other.Video") == []


def test_fanout_names_follows_picked_variant():
    from core.autosave import fanout_names, rename_map
    subs = ["t.S01E01.chs.srt", "t.S01E01.chs&eng.srt",
            "t.S01E02.chs.srt", "t.S01E02.chs&eng.srt",
            "t.S01E03.chs.srt"]  # E03 lacks the bilingual twin
    siblings = ["Show.S01E01", "Show.S01E03"]
    mapping = rename_map(subs, "Show.S01E02", siblings)
    picked = "t.S01E02.chs&eng.srt"
    out = fanout_names(mapping, picked, video_stem="Show.S01E02")
    # one file per remaining episode: the picked variant, else the best one
    assert sorted(out) == ["t.S01E01.chs&eng.srt", "t.S01E03.chs.srt"]


def test_fanout_names_movie_twins_stay_home():
    from core.autosave import fanout_names, rename_map
    subs = ["Movie.chs.srt", "Movie.chs&eng.srt"]
    mapping = rename_map(subs, "Movie.2010", [])
    # everything maps to the playing video: the player stores the pick,
    # nothing is copied out
    assert fanout_names(mapping, "Movie.chs&eng.srt", video_stem="Movie.2010") == []


def test_fanout_names_without_pick():
    from core.autosave import fanout_names, rename_map
    subs = ["t.S01E01.srt", "t.S01E03.srt"]
    mapping = rename_map(subs, "Show.S01E02", ["Show.S01E01", "Show.S01E03"])
    # pack misses the playing episode: other episodes still fan out
    assert sorted(fanout_names(mapping, "", video_stem="Show.S01E02")) == subs


def test_is_bilingual_markers():
    from core.autosave import is_bilingual
    for name in ("X.chs&eng.ass", "X.cht+eng.ass", "X.chs.eng.srt", "X.eng&chs.srt",
                 "X.简英.srt", "X.繁英.ass", "X.中英双语.srt", "X.简体&英文.srt"):
        assert is_bilingual(name), name
    for name in ("X.chs.ass", "X.eng.srt", "X.England.chs.srt", "X.简体.srt"):
        assert not is_bilingual(name), name


def test_lang_tag_composites():
    from core.autosave import lang_tag
    assert lang_tag("X.chs&eng.ass") == "chs&eng"
    assert lang_tag("X.cht+eng.ass") == "cht+eng"
    assert lang_tag("X.chs.ass") == "chs"


def test_rename_map_composite_tag_distinct():
    from core.autosave import rename_map
    subs = ["S.S01E02.chs&eng.ass", "S.S01E02.chs.ass"]
    mapping = rename_map(subs, "Show.S01E02", [])
    assert set(mapping.values()) == {"Show.S01E02.chs&eng", "Show.S01E02.chs"}
