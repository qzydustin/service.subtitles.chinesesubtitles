# -*- coding: utf-8 -*-
"""Offline tests for the Kodi adapter's query building (needs Kodistubs)."""
import os
import sys

import pytest

pytest.importorskip("xbmc")  # Kodistubs provides the xbmc modules

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
lib_dir = os.path.join(base_dir, "resources", "lib")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)

import xbmc
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
    def __init__(self, tag=None, filename=""):
        self.tag, self.filename = tag, filename

    def getVideoInfoTag(self):
        if self.tag is None:
            raise RuntimeError("not playing")
        return self.tag

    def getPlayingFile(self):
        return "/tv/" + self.filename


def with_player(monkeypatch, player):
    monkeypatch.setattr(xbmc, "Player", lambda: player)


def test_query_tv_episode(monkeypatch):
    tag = FakeTag(title="Breakage", tvshow="绝命毒师", season=2, episode=5, year=2009)
    with_player(monkeypatch, FakePlayer(tag, "breaking.bad.s02e05.mkv"))
    query = plugin.current_query()
    assert query == plugin.WorkQuery(title="绝命毒师", year="2009", season="2",
                                     episode="5", is_tv=True)


def test_query_movie_prefers_display_title(monkeypatch):
    tag = FakeTag(title="盗梦空间", original="Inception", year=2010)
    with_player(monkeypatch, FakePlayer(tag, "inception.mkv"))
    query = plugin.current_query()
    assert query == plugin.WorkQuery(title="盗梦空间", year="2010", is_tv=False)


def test_query_movie_falls_back_to_original_title(monkeypatch):
    tag = FakeTag(original="Inception", year=2010)
    with_player(monkeypatch, FakePlayer(tag, "x.mkv"))
    query = plugin.current_query()
    assert query.title == "Inception" and query.year == "2010"


def test_query_unscraped_filename_fallback(monkeypatch):
    with_player(monkeypatch, FakePlayer(FakeTag(), "Show.Name.S02E05.720p.x264-GRP.mkv"))
    query = plugin.current_query()
    assert query == plugin.WorkQuery(title="Show Name", season="2", episode="5", is_tv=True)


def test_query_specials_drop_season_zero(monkeypatch):
    tag = FakeTag(tvshow="神秘博士", season=0, episode=3, year=2005)
    with_player(monkeypatch, FakePlayer(tag, "x.mkv"))
    query = plugin.current_query()
    assert query.is_tv and query.season == "" and query.episode == "3"


def test_query_nothing_playing(monkeypatch):
    with_player(monkeypatch, FakePlayer())
    assert plugin.current_query() is None
