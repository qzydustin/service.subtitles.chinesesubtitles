# -*- coding: utf-8 -*-
"""Kodi plugin layer: adapts the xbmc runtime to the pure core library."""
import json
import os
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
from core.autosave import VIDEO_EXTS, playback_pick, rename_map
from core.filter import apply_filters
from core.matcher import FOLDER_SEASON_RE, episode_marker, parse_filename, season_number
from core.models import FORMATS, LANGS, SOURCES, WorkQuery, build_label, language_meta

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
    keys = (["filter_bilingual"]
            + [f"filter_src_{k}" for k in SOURCES]
            + [f"filter_lang_{k}" for k in LANGS]
            + [f"filter_fmt_{k}" for k in FORMATS])
    return {k: __addon__.getSetting(k) == "true" for k in keys}


# ---- actions ----

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
            num = season_number(m.group(1) or m.group(2) or m.group(3))
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
    dbid = xbmc.getInfoLabel("VideoPlayer.TvShowDBID")
    if not dbid or not dbid.isdigit():
        return ""
    details = jsonrpc("VideoLibrary.GetTVShowDetails",
                      {"tvshowid": int(dbid),
                       "properties": ["originaltitle"]}).get("tvshowdetails", {})
    return details.get("originaltitle", "").strip()


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


def jsonrpc(method, params):
    """One JSON-RPC roundtrip; {} when anything fails."""
    try:
        reply = json.loads(xbmc.executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params})))
        return reply.get("result", {})
    except Exception as e:
        log(f"JSON-RPC {method} failed: {e}", xbmc.LOGWARNING)
        return {}


def fanout_folder(video_folder):
    """Where pack/twin copies go, mirroring the player's subtitle storage
    mode: the custom subtitle folder when chosen (usually because the video
    folder is read-only), else next to the video. Both places are scanned
    for external subtitles at playback."""
    mode = jsonrpc("Settings.GetSettingValue",
                   {"setting": "subtitles.storagemode"}).get("value")
    if mode == 1:
        return xbmcvfs.translatePath("special://subtitles")
    return video_folder


def autosave(result):
    """Fan pack subtitles out to their videos and return the path to load
    now ('' when no confident pick exists).

    The returned file itself is NOT copied here: Kodi core stores it under
    the player's subtitle storage settings, which this addon shouldn't
    second-guess. Everything else in the download — other episodes of a
    pack, language twins — core never touches, so those are copied here.
    """
    try:
        video_path = xbmc.Player().getPlayingFile()
    except Exception as e:
        log(f"autosave skipped, nothing playing: {e}", xbmc.LOGWARNING)
        return ""
    stem = os.path.splitext(os.path.basename(video_path))[0]
    video_folder = os.path.dirname(video_path)
    if not video_folder or not stem:
        return ""
    try:
        _, files = xbmcvfs.listdir(video_folder)
    except Exception as e:
        log(f"autosave: list {video_folder} failed: {e}", xbmc.LOGWARNING)
        return ""
    siblings = [os.path.splitext(f)[0] for f in files if f.lower().endswith(VIDEO_EXTS)]
    mapping = rename_map(result.files, stem, siblings, season=episode_marker(stem)[0])
    settings = filter_settings()
    preferred = tuple(l for l in LANGS if settings.get(f"filter_lang_{l}")) or LANGS
    picked = playback_pick(mapping, stem, preferred=preferred)

    folder = fanout_folder(video_folder)
    fallback = xbmcvfs.translatePath("special://subtitles")

    def copy_out(path, target):
        """Copy into the fan-out folder; an unwritable video folder switches
        the remaining copies to the subtitle storage folder. A vobsub .sub
        takes its .idx index along."""
        nonlocal folder
        dst = folder.rstrip("/") + "/" + target
        ok = xbmcvfs.copy(path, dst)
        if not ok and fallback and folder != fallback:
            folder = fallback
            dst = folder.rstrip("/") + "/" + target
            ok = xbmcvfs.copy(path, dst)
        if not ok:
            log(f"autosave: copy to {dst} failed", xbmc.LOGWARNING)
            return
        log(f"autosave: {os.path.basename(path)} -> {dst}")
        if os.path.splitext(path)[1].lower() == ".sub":
            idx_src = os.path.splitext(path)[0] + ".idx"
            idx_dst = os.path.splitext(dst)[0] + ".idx"
            if xbmcvfs.exists(idx_src) and xbmcvfs.copy(idx_src, idx_dst):
                log(f"autosave: {os.path.basename(idx_src)} -> {idx_dst}")

    for name, path in zip(result.files, result.paths):
        if mapping.get(name) and name != picked:
            copy_out(path, mapping[name] + os.path.splitext(name)[1].lower())
    if not picked:
        return ""
    return result.paths[result.files.index(picked)]


def do_download(link, provider):
    clean_temp()
    log(f"download {provider}: {link}")
    result = service.download(link, provider, __temp__, log=log, backend=extract_archive)
    if result.status == "invalid":
        icon = os.path.join(__cwd__, "resources", "icon.png")
        xbmcgui.Dialog().notification(__scriptname__, __language__(30902), icon, 4000)
    if result.reason:
        icon = os.path.join(__cwd__, "resources", "icon.png")
        xbmcgui.Dialog().notification(__scriptname__, result.reason, icon, 4000)
    if not result.files:
        return []
    picked = autosave(result)
    if picked:
        return [picked]
    if len(result.files) == 1:
        return [result.paths[0]]
    # nothing maps to the playing video: let the user pick
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
