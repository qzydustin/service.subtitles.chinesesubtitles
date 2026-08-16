# -*- coding: utf-8 -*-
"""Offline tests for the Kodi adapter's query building (needs Kodistubs)."""
import json
import os
import sys

import pytest

pytest.importorskip("xbmc")  # Kodistubs provides the xbmc modules

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
lib_dir = os.path.join(base_dir, "resources", "lib")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)

import xbmc
import xbmcvfs
from kodi import plugin


class FakeTag:
    def __init__(self, title="", tvshow="", season=0, episode=0, year=0, original=""):
        self._data = dict(title=title, tvshow=tvshow, season=season,
                          episode=episode, year=year, original=original)

    def getTitle(self):
        return self._data["title"]

    def getTVShowTitle(self):
        return self._data["tvshow"]

    def getSeason(self):
        return self._data["season"]

    def getEpisode(self):
        return self._data["episode"]

    def getYear(self):
        return self._data["year"]

    def getOriginalTitle(self):
        return self._data["original"]


class FakePlayer:
    def __init__(self, tag=None, filename="", path=None):
        self.tag, self.path = tag, path or ("/tv/" + filename)

    def getVideoInfoTag(self):
        if self.tag is None:
            raise RuntimeError("not playing")
        return self.tag

    def getPlayingFile(self):
        return self.path


class FakeAddon:
    def __init__(self, settings):
        self._settings = settings

    def getSetting(self, key):
        return self._settings.get(key, "")


def addon_with(**overrides):
    """Addon whose settings are all on, except the overrides
    (given as unprefixed keys like lang_eng=False)."""
    ids = (["filter_bilingual"]
           + [f"filter_src_{k}" for k in plugin.SOURCES]
           + [f"filter_lang_{k}" for k in plugin.LANGS]
           + [f"filter_fmt_{k}" for k in plugin.FORMATS])
    values = {i: "true" for i in ids}
    values["filter_bilingual"] = "false"  # bilingual-only stays off by default
    values.update({f"filter_{k}": "false" for k in overrides})
    return FakeAddon(values)


def with_player(monkeypatch, player):
    monkeypatch.setattr(xbmc, "Player", lambda: player)


def test_query_tv_episode(monkeypatch):
    tag = FakeTag(title="Breakage", tvshow="绝命毒师", season=2, episode=5, year=2009)
    monkeypatch.setattr(plugin, "show_original_title", lambda: "")
    with_player(monkeypatch, FakePlayer(tag, "breaking.bad.s02e05.mkv"))
    query = plugin.current_query()
    assert query == plugin.WorkQuery(title="绝命毒师", year="2009", season="2",
                                     episode="5", is_tv=True)


def test_query_tv_combines_show_original_title(monkeypatch):
    tag = FakeTag(title="Breakage", tvshow="绝命毒师", season=2, episode=5, year=2009)
    monkeypatch.setattr(plugin, "show_original_title", lambda: "Breaking Bad")
    with_player(monkeypatch, FakePlayer(tag, "breaking.bad.s02e05.mkv"))
    query = plugin.current_query()
    assert query == plugin.WorkQuery(title="绝命毒师 Breaking Bad",
                                     alt_titles=["绝命毒师", "Breaking Bad"],
                                     year="2009", season="2", episode="5",
                                     is_tv=True)


def test_show_original_title_lookup(monkeypatch):
    reply = json.dumps({"result": {"tvshowdetails": {"originaltitle": "Friends"}}})
    monkeypatch.setattr(xbmc, "getInfoLabel", lambda label: "42" if label == "VideoPlayer.TvShowDBID" else "")
    monkeypatch.setattr(xbmc, "executeJSONRPC", lambda req: reply)
    assert plugin.show_original_title() == "Friends"


def test_show_original_title_unavailable(monkeypatch):
    monkeypatch.setattr(xbmc, "getInfoLabel", lambda label: "")
    assert plugin.show_original_title() == ""
    monkeypatch.setattr(xbmc, "getInfoLabel", lambda label: "42")
    monkeypatch.setattr(xbmc, "executeJSONRPC", lambda req: "not json")
    assert plugin.show_original_title() == ""


def test_query_movie_combines_bilingual_titles(monkeypatch):
    tag = FakeTag(title="盗梦空间", original="Inception", year=2010)
    with_player(monkeypatch, FakePlayer(tag, "inception.mkv"))
    query = plugin.current_query()
    assert query == plugin.WorkQuery(title="盗梦空间 Inception",
                                     alt_titles=["盗梦空间", "Inception"],
                                     year="2010", is_tv=False)


def test_query_movie_without_original(monkeypatch):
    tag = FakeTag(title="盗梦空间", year=2010)
    with_player(monkeypatch, FakePlayer(tag, "x.mkv"))
    query = plugin.current_query()
    assert query == plugin.WorkQuery(title="盗梦空间", year="2010", is_tv=False)


def test_query_unscraped_filename_fallback(monkeypatch):
    with_player(monkeypatch, FakePlayer(FakeTag(), "Show.Name.S02E05.720p.x264-GRP.mkv"))
    query = plugin.current_query()
    assert query == plugin.WorkQuery(title="Show Name", season="2", episode="5", is_tv=True)


def test_query_kodi_title_echo_parses_release_name(monkeypatch):
    # non-library playback: Kodi labels the item with the filename stem
    name = "Show.Name.S02E05.720p.x264-GRP"
    tag = FakeTag(title=name)
    with_player(monkeypatch, FakePlayer(tag, name + ".mkv"))
    query = plugin.current_query()
    assert query == plugin.WorkQuery(title="Show Name", season="2", episode="5", is_tv=True)


def test_query_hash_filename_rescued_by_folder(monkeypatch):
    path = "/media/TV/电锯人 第一季/bd26e8f2b1ee9c.mkv"
    with_player(monkeypatch, FakePlayer(FakeTag(), path=path))
    query = plugin.current_query()
    assert query == plugin.WorkQuery(title="电锯人", season="1", is_tv=True)


def test_query_hash_filename_generic_folder_not_used(monkeypatch):
    path = "/Downloads/bd26e8f2b1ee9c.mkv"
    with_player(monkeypatch, FakePlayer(FakeTag(), path=path))
    query = plugin.current_query()
    # no better source than the hash itself; the search will simply miss
    assert query.title == "bd26e8f2b1ee9c"


def test_query_specials_drop_season_zero(monkeypatch):
    tag = FakeTag(tvshow="神秘博士", season=0, episode=3, year=2005)
    with_player(monkeypatch, FakePlayer(tag, "x.mkv"))
    query = plugin.current_query()
    assert query.is_tv and query.season == "" and query.episode == "3"


def test_query_nothing_playing(monkeypatch):
    with_player(monkeypatch, FakePlayer())
    assert plugin.current_query() is None


def test_fanout_folder_follows_storage_mode(monkeypatch):
    monkeypatch.setattr(plugin, "jsonrpc", lambda method, params: {"value": 1})
    monkeypatch.setattr(xbmcvfs, "translatePath", lambda p: "/custom/subs" if p == "special://subtitles" else "")
    assert plugin.fanout_folder("/videos/Show") == "/custom/subs"
    monkeypatch.setattr(plugin, "jsonrpc", lambda method, params: {"value": 0})
    assert plugin.fanout_folder("/videos/Show") == "/videos/Show"
    monkeypatch.setattr(plugin, "jsonrpc", lambda method, params: {})  # lookup failed
    assert plugin.fanout_folder("/videos/Show") == "/videos/Show"


def test_filter_settings_drop_the_filter_prefix(monkeypatch):
    monkeypatch.setattr(plugin, "__addon__", addon_with(lang_eng=False, src_machine=False))
    settings = plugin.filter_settings()
    assert settings["lang_eng"] is False and settings["lang_chs"] is True
    assert settings["src_machine"] is False and settings["src_official"] is True
    assert not any(k.startswith("filter_") for k in settings)


def test_filter_settings_drive_core_filter(monkeypatch):
    # regression: the adapter's dict must be readable by core's apply_filters
    from core.filter import apply_filters
    from core.models import Subtitle, Tags

    monkeypatch.setattr(plugin, "__addon__", addon_with(src_machine=False))
    good = Subtitle("a.srt", "l1", Tags(lang=["chs"], fmt=["srt"], source=["official"]))
    machine = Subtitle("b.srt", "l2", Tags(lang=["chs"], fmt=["srt"], source=["machine"]))
    assert apply_filters([good, machine], plugin.filter_settings()) == [good]
