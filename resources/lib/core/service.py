# -*- coding: utf-8 -*-
"""Use-case orchestration: work resolution, two-site search, download."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from .http import noop_log
from .matcher import works_match
from .subhd import SubhdProvider
from .zimuku import ZimukuProvider

# Providers are cheap to build; one entry point constructs what it needs.
PROVIDERS = {"subhd": SubhdProvider, "zimuku": ZimukuProvider}


def work_label(work):
    """Picker label such as `绝命毒师 第二季 Breaking Bad (2009) [SUBHD+ZIMUKU]`."""
    year = f" ({work.year})" if work.year else ""
    badges = "+".join(work.anchors.keys()).upper()
    return f"{work.title}{year} [{badges}]"


def aggregate(subhd_works, zimuku_works, query=None):
    """Merge both sites' work lists into picker rows.

    Each Zimuku work joins the SubHD row it matches unambiguously; zero or
    several matching SubHD works leave it as its own row (never guess between
    same-named remakes). Unmatched SubHD works stay as rows too, so one dead
    site never hides the other's results. Duplicate Zimuku pages of the same
    work all merge into the row, keeping every page reachable.
    """
    rows = list(subhd_works)
    for zw in zimuku_works:
        matches = [row for row in rows[:len(subhd_works)]
                   if works_match(zw.title, row.title)]
        if len(matches) == 1:
            row = matches[0]
            row.anchors.setdefault("zimuku", []).extend(zw.anchors.get("zimuku", []))
            row.year = row.year or zw.year
        else:
            rows.append(zw)
    return order_works(rows, query)


def order_works(rows, query=None):
    """Season match first, then closeness to the query year, then site order."""
    season = str((query.season or "") if query else "").strip()
    year = str((query.year or "") if query else "").strip()
    try:
        target = int(year) if year else None
    except ValueError:
        target = None

    def year_distance(w):
        # provider years come from a (19|20)xx regex, so int() always holds
        return abs(int(w.year) - target) if (target is not None and w.year) else 9999

    rows.sort(key=lambda w: (
        0 if (season and str(w.season or "") == season) else 1,
        year_distance(w),
        0 if "subhd" in w.anchors else 1,
    ))
    return rows


def _find_rows(query, log):
    """Search both sites in parallel and aggregate the work rows."""

    def fetch(name):
        try:
            return list(PROVIDERS[name](log=log).find_works(query) or [])
        except Exception as e:
            log(f"{name}: find_works failed: {e}")
            return []

    with ThreadPoolExecutor(max_workers=2) as pool:
        subhd_future = pool.submit(fetch, "subhd")
        zimuku_future = pool.submit(fetch, "zimuku")
        return aggregate(subhd_future.result(), zimuku_future.result(), query)


def resolve_work(query, choose=None, log=noop_log):
    """Resolve the query to a single work via both sites, in parallel.

    When the primary title finds no works, the alt_titles are tried in order
    (e.g. bilingual combined -> original -> display title). Returns None when
    nothing is found or the picker is cancelled. A single row is returned
    without showing the picker; `choose(title, options)` otherwise decides
    (headless default: first row).
    """
    rows = []
    for i, title in enumerate([query.title] + list(query.alt_titles)):
        if i:
            log(f"no works for '{query.title}', retrying with '{title}'")
            query = replace(query, title=title, alt_titles=[])
        rows = _find_rows(query, log)
        if rows:
            break
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    index = choose("Select Work", [work_label(w) for w in rows]) if choose else 0
    if index is None or not 0 <= index < len(rows):
        return None
    return rows[index]


def search_all(query, work, log=noop_log):
    """Search every site the work carries an anchor for; tags.provider marks
    each result's origin. Site failures degrade to empty lists."""
    def fetch(name):
        if not work or name not in work.anchors:
            return []
        try:
            return list(PROVIDERS[name](log=log).search(query, work) or [])
        except Exception as e:
            log(f"{name}: search failed: {e}")
            return []

    subtitles = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [(name, pool.submit(fetch, name)) for name in PROVIDERS]
        for name, future in futures:
            for s in future.result():
                s.tags.provider = name
                subtitles.append(s)
    return subtitles


def download(link, provider="subhd", dest="", log=noop_log, backend=None):
    """Download one subtitle into dest via the named provider."""
    cls = PROVIDERS.get(provider) or next(iter(PROVIDERS.values()))
    return cls(log=log, backend=backend).download(link, dest)
