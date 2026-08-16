# -*- coding: utf-8 -*-
"""Use-case orchestration: zimuku work resolution, douban bridge, download."""
from dataclasses import replace

from .http import noop_log
from .subhd import SubhdProvider
from .zimuku import ZimukuProvider

# Providers are cheap to build; one entry point constructs what it needs.
PROVIDERS = {"subhd": SubhdProvider, "zimuku": ZimukuProvider}


def order_works(rows, query=None):
    """Season match first, then closeness to the query year."""
    season = str((query.season or "") if query else "").strip()
    year = str((query.year or "") if query else "").strip()
    try:
        target = int(year) if year else None
    except ValueError:
        target = None

    # provider years come from a (19|20)xx regex, so int() always holds
    rows.sort(key=lambda w: (
        0 if (season and str(w.season or "") == season) else 1,
        abs(int(w.year) - target) if (target is not None and w.year) else 9999,
    ))
    return rows


def _zimuku_rows(query, log):
    """Search Zimuku for works, walking a query ladder until rows appear.

    Measured: the bilingual combined title leaves few junk rows ("Friends"
    alone: 100 works; "老友记 Friends": 11) and a year suffix pins remakes
    ("悲惨世界 Les Misérables 2012": exactly the 2012 film). A known season
    never goes into the query ("老友记 第10季" once matched 第一季) — the rows
    are filtered down to that season plus season-less pack entries instead.
    """
    attempts = ([f"{query.title} {query.year}"] if query.year else []) \
        + [query.title] + [t for t in query.alt_titles if t]
    zimuku = PROVIDERS["zimuku"](log=log)
    for i, title in enumerate(dict.fromkeys(attempts)):
        if i:
            log(f"no works for '{query.title}', retrying with '{title}'")
        try:
            rows = list(zimuku.find_works(replace(query, title=title)) or [])
        except Exception as e:
            log(f"zimuku: find_works failed: {e}")
            rows = []
        if query.season:
            rows = [w for w in rows if w.season in ("", query.season)]
        if rows:
            return order_works(rows, query)
    return []


def resolve_work(query, choose=None, log=noop_log):
    """Resolve the query to one work via Zimuku, then bridge it to SubHD.

    Zimuku groups subtitles by work and searches bilingual titles, years
    and seasons well, so it is the only work index. After the pick, one
    fetch of the chosen work page yields its Douban subject id — SubHD
    serves the same movie or season under /d/{douban id}, joining the
    sites by id instead of fuzzy title matching — and the page's subtitle
    list, preloaded for search_all. Returns None when nothing is found or
    the picker is cancelled. A single row skips the picker;
    `choose(title, options)` otherwise decides (headless default: first).
    """
    rows = _zimuku_rows(query, log)
    if not rows:
        return None
    if len(rows) == 1:
        work = rows[0]
    else:
        index = choose("Select Work", [w.title for w in rows]) if choose else 0
        if index is None or not 0 <= index < len(rows):
            return None
        work = rows[index]
    _bridge(query, work, log)
    return work


def _bridge(query, work, log):
    """Fetch the picked Zimuku page once: its Douban id becomes the SubHD
    anchor and its subtitles preload the work, so search_all only has to
    fetch SubHD. A page without an id (or an unreachable one) leaves the
    work Zimuku-only; search_all then degrades to the single site.
    """
    url = (work.anchors.get("zimuku") or [""])[0]
    if not url:
        return
    try:
        douban, subs = PROVIDERS["zimuku"](log=log).work_page(query, url)
    except Exception as e:
        log(f"zimuku: work page fetch failed: {e}")
        return
    if douban:
        work.anchors["subhd"] = [f"/d/{douban}"]
    work.preloaded["zimuku"] = subs


def search_all(query, work, log=noop_log):
    """Collect the subtitles of every anchored site; tags.provider marks
    each result's origin. Results preloaded during resolution pass through
    as-is (normally only SubHD is fetched here); site failures degrade to
    empty lists."""
    subtitles = []
    for name, cls in PROVIDERS.items():
        found = work.preloaded.get(name) if work else None
        if found is None and work and name in work.anchors:
            try:
                found = list(cls(log=log).search(query, work) or [])
            except Exception as e:
                log(f"{name}: search failed: {e}")
                found = []
        for s in found or ():
            s.tags.provider = name
            subtitles.append(s)
    return subtitles


def download(link, provider="subhd", dest="", log=noop_log, backend=None):
    """Download one subtitle into dest via the named provider."""
    cls = PROVIDERS.get(provider) or PROVIDERS["subhd"]
    return cls(log=log, backend=backend).download(link, dest)
