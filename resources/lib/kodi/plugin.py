# -*- coding: utf-8 -*-
"""Kodi plugin layer: adapts the xbmc runtime to the pure core library."""
import json
import os
import re
import sys
import urllib.parse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

_LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from core import service
from core.archive import SUBTITLE_EXTS, shorten_names
from core.filter import apply_filters
from core.matcher import CN_NUM, parse_filename
from core.models import WorkQuery, build_label, language_meta

__addon__ = xbmcaddon.Addon()
__scriptid__ = __addon__.getAddonInfo("id")
__scriptname__ = __addon__.getAddonInfo("name")
__cwd__ = xbmcvfs.translatePath(__addon__.getAddonInfo("path"))
__profile__ = xbmcvfs.translatePath(__addon__.getAddonInfo("profile"))
__temp__ = xbmcvfs.translatePath(os.path.join(__profile__, "temp"))
__language__ = __addon__.getLocalizedString


def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"{__scriptname__} :: {message}", level=level)


# ---- host adapters: what core expects from its runtime ----

def choose(title, options):
    """Dialog picker for core flows; returns None when the user cancels."""
    sel = xbmcgui.Dialog().select(title, options)
    return None if sel < 0 else sel


def extract_archive(path):
    """rar/7z (+ other Kodi-supported archives) via vfs add-ons; zip stays in core."""
    ext = path.split(".")[-1].lower()
    protocol = "rar" if ext == "rar" else "archive"
    url = f"{protocol}://{urllib.parse.quote_plus(path)}"
    try:
        dirs, files = xbmcvfs.listdir(url)
    except Exception as e:
        log(f"vfs extract failed for {path}: {e}", xbmc.LOGWARNING)
        return "", []
    if "__MACOSX" in dirs:
        dirs.remove("__MACOSX")
    target = url
    if not any(f.lower().endswith(SUBTITLE_EXTS) for f in files) and dirs:
        target = url + "/" + dirs[0]
        dirs, files = xbmcvfs.listdir(target)
    return target, [f for f in files if f.lower().endswith(SUBTITLE_EXTS)]


def clean_temp():
    """Wipe the addon temp dir so every download starts fresh."""
    temp = __temp__.replace("\\", "/").rstrip("/")
    if not xbmcvfs.exists(temp):
        xbmcvfs.mkdirs(temp)
        return

    def wipe(path):
        try:
            dirs, files = xbmcvfs.listdir(path)
        except Exception as e:
            log(f"list {path} failed: {e}", xbmc.LOGWARNING)
            return
        for name in files:
            if not xbmcvfs.delete(f"{path}/{name}"):
                log(f"delete {path}/{name} failed", xbmc.LOGWARNING)
        for name in dirs:
            wipe(f"{path}/{name}")
            xbmcvfs.rmdir(f"{path}/{name}")

    wipe(temp)


def filter_settings():
    """Read addon settings into the plain dict core's filter expects."""
    keys = ("filter_bilingual",
            "filter_src_official", "filter_src_reprint", "filter_src_original",
            "filter_src_ai", "filter_src_machine",
            "filter_lang_chs", "filter_lang_cht", "filter_lang_eng",
            "filter_fmt_ass", "filter_fmt_srt", "filter_fmt_ssa", "filter_fmt_sub",
            "filter_fmt_sup", "filter_fmt_vtt")
    return {k: __addon__.getSetting(k) == "true" for k in keys}


# ---- actions ----

# trailing season marker in folder names: "电锯人 第一季", "Show Season 2", "Show S02"
FOLDER_SEASON_RE = re.compile(
    r'(?:第([一二三四五六七八九十\d]+)\s*季|season\s*(\d+)|S(\d{1,2}))\s*$', re.I)
GENERIC_FOLDERS = {"movie", "movies", "tv", "tvshows", "shows", "series",
                   "video", "videos", "media", "download", "downloads", "新建文件夹"}


def _hashlike(title):
    """Release-name residue like 'bd26e8f2b1ee': no spaces, digits and letters mixed."""
    return (len(title) >= 8 and " " not in title
            and any(c.isdigit() for c in title) and any(c.isalpha() for c in title))


def release_query(stem, folder):
    """WorkQuery for unscraped items: parse the release name; the parent
    folder (one show per folder, season marker stripped) rescues hash-like
    or empty filenames."""
    parsed = parse_filename(stem)
    title = parsed["title"]
    if not title or _hashlike(title):
        folder = folder.strip()
        season = ""
        m = FOLDER_SEASON_RE.search(folder)
        if m:
            raw = m.group(1) or m.group(2) or m.group(3)
            num = int(raw) if raw.isdigit() else CN_NUM.get(raw, 0)
            season = str(num) if num else ""
            folder = folder[:m.start()].strip(" .-_")
        folder_parsed = parse_filename(folder)
        if folder_parsed["title"] and folder_parsed["title"].lower() not in GENERIC_FOLDERS:
            return WorkQuery(
                title=folder_parsed["title"],
                year=parsed["year"] or folder_parsed["year"],
                season=parsed["season"] or folder_parsed["season"] or season,
                episode=parsed["episode"],
                is_tv=bool(parsed["season"] or parsed["episode"]
                           or folder_parsed["season"] or season))
    return WorkQuery(title=title, year=parsed["year"],
                     season=parsed["season"], episode=parsed["episode"],
                     is_tv=bool(parsed["season"] or parsed["episode"]))


def show_original_title():
    """The playing show's original title from the Kodi library.

    The episode tag exposes no original show title (only getTVShowTitle),
    so ask the video library via JSON-RPC; '' when unavailable."""
    try:
        dbid = xbmc.getInfoLabel("VideoPlayer.TvShowDBID")
        if not dbid or not dbid.isdigit():
            return ""
        reply = json.loads(xbmc.executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "VideoLibrary.GetTVShowDetails",
            "params": {"tvshowid": int(dbid), "properties": ["originaltitle"]},
        })))
        details = reply.get("result", {}).get("tvshowdetails", {})
        return details.get("originaltitle", "").strip()
    except Exception as e:
        log(f"library lookup for show original title failed: {e}", xbmc.LOGWARNING)
        return ""


def current_query():
    """Build a WorkQuery from the playing video's info tag.

    The typed tag API is the single source of truth (int season/episode/year,
    no localized info-label strings); release-name parsing covers unscraped
    files. Returns None when no usable item is playing.
    """
    player = xbmc.Player()
    try:
        tag = player.getVideoInfoTag()
        path = player.getPlayingFile()
    except Exception as e:
        log(f"no playing video metadata: {e}", xbmc.LOGWARNING)
        return None
    filename = os.path.basename(path)
    stem = os.path.splitext(filename)[0]
    tvshow = tag.getTVShowTitle().strip()
    display = (tvshow or tag.getTitle()).strip()
    original = tag.getOriginalTitle().strip()
    year = str(tag.getYear()) if tag.getYear() else ""
    # unscraped: no titles at all, or Kodi echoed the release name back as the
    # title (its label for non-library items) — a dotted release name queried
    # verbatim finds nothing under token-AND matching
    if not original and (not display or display == stem):
        query = release_query(stem, os.path.basename(os.path.dirname(path)))
        log(f"unscraped item; release-name parse: {query}")
        return query
    if tvshow:
        season, episode = tag.getSeason(), tag.getEpisode()
        fields = dict(year=year,
                      season=str(season) if season > 0 else "",
                      episode=str(episode) if episode > 0 else "",
                      is_tv=True)
        original = show_original_title()
        if original and original != tvshow:
            # same bilingual precision win as movies: "老友记 Friends" returns
            # only Friends-related rows, "老友记" drags 7 noise rows along
            return WorkQuery(title=f"{tvshow} {original}",
                             alt_titles=[tvshow, original], **fields)
        return WorkQuery(title=tvshow, **fields)
    # movies: sites list bilingual titles and match queries by token-AND
    # (substring level), so "中文 英文" hits exactly and rescues single
    # common-word titles ("小丑回魂 It" -> the right 4 works, "It" -> 123
    # junk rows); single-language titles follow as zero-result fallbacks
    # in the order Chinese (usually douban-aligned) then original
    if display and original and display != original:
        return WorkQuery(title=f"{display} {original}",
                         alt_titles=[display, original], year=year)
    return WorkQuery(title=original or display, year=year)


def do_search(query):
    log(f"search query: {query}")
    work = service.resolve_work(query, choose=choose, log=log)
    if not work:
        return

    subtitles = service.search_all(query, work, log=log)
    log(f"found {len(subtitles)} raw results")
    if not subtitles:
        return
    subtitles = apply_filters(subtitles, filter_settings(), log)
    list_subtitles(subtitles)


def list_subtitles(subtitles):
    handle = int(sys.argv[1])
    for s in subtitles:
        name, flag = language_meta(s.tags)
        label = f"[{s.tags.provider.upper()}]{build_label(s.tags, filename=s.filename)}"
        item = xbmcgui.ListItem(label=name, label2=label)
        item.setArt({"icon": "0", "thumb": flag})
        item.setProperty("sync", "false")
        item.setProperty("hearing_imp", "false")
        url = ("plugin://%s/?action=download&link=%s&provider=%s"
               % (__scriptid__, urllib.parse.quote(s.link, safe=""), s.tags.provider))
        xbmcplugin.addDirectoryItem(handle=handle, url=url, listitem=item, isFolder=False)


def do_download(link, provider):
    clean_temp()
    log(f"download {provider}: {link}")
    result = service.download(link, provider, __temp__, log=log, backend=extract_archive)
    if result.status == "invalid":
        icon = os.path.join(__cwd__, "resources", "icon.png")
        xbmcgui.Dialog().notification(__scriptname__, __language__(30902), icon, 4000)
    if not result.files:
        return []
    if len(result.files) == 1:
        return [result.paths[0]]
    display = result.display_names if __addon__.getSetting("cutsubfn") == "true" else result.files
    sel = choose("Choose Subtitle", display)
    if sel is None:
        sel = 0
    return [result.paths[min(sel, len(result.paths) - 1)]]


# ---- entry ----

def run():
    params = {}
    if len(sys.argv) >= 3 and len(sys.argv[2]) >= 2:
        for key, values in urllib.parse.parse_qs(
                sys.argv[2].lstrip("?"), keep_blank_values=True).items():
            params[key] = values[0]
    log(f"handle params: {params}")

    if __addon__.getSetting("proxy_follow_kodi") != "true":
        proxy = ("" if __addon__.getSetting("proxy_use") != "true"
                 else __addon__.getSetting("proxy_server"))
        os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = proxy

    action = params.get("action")
    if action in ("search", "manualsearch"):
        if "searchstring" in params:
            query = WorkQuery(title=params["searchstring"])
        else:
            query = current_query()
        if query and query.title:
            do_search(query)
    elif action == "download":
        for path in do_download(params["link"], params.get("provider")):
            xbmcplugin.addDirectoryItem(
                handle=int(sys.argv[1]),
                url=path,
                listitem=xbmcgui.ListItem(label=path),
                isFolder=False)

    xbmcplugin.endOfDirectory(int(sys.argv[1]))
