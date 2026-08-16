# -*- coding: utf-8 -*-
"""Title parsing and matching for aggregating works found on both sites."""
import re

CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
SEASON_RE = re.compile(r'第([一二三四五六七八九十\d]+)\s*季|season\s*(\d+)', re.I)
YEAR_RE = re.compile(r'[（(]\s*((?:19|20)\d{2})\s*[)）]')


def _season_number(raw):
    """Chinese-numeral or digit season string -> int (0 when unparsable)."""
    return int(raw) if raw.isdigit() else CN_NUM.get(raw, 0)


def parse_meta(title):
    """Title -> (normalized token set, season str, year str)."""
    year = season = ""
    m = YEAR_RE.search(title)
    if m:
        year, title = m.group(1), YEAR_RE.sub(" ", title)
    m = SEASON_RE.search(title)
    if m:
        season = str(_season_number(m.group(1) or m.group(2)))
        if season == "0":  # season counts the table can't parse (eleven and up) mean none
            season = ""
        title = SEASON_RE.sub(" ", title)
    tokens = set(re.sub(r"[^\w\s]", " ", title.lower()).split()) - {"the"}
    return tokens, season, year


def works_match(a, b):
    """Whether two site titles refer to the same work (season equal, years
    compatible, same normalized token set). Immune to word order, punctuation
    and case; a missing season on either side means season must be empty on
    both ('movie' vs 'season 2' never connects)."""
    ta, sa, ya = parse_meta(a)
    tb, sb, yb = parse_meta(b)
    if sa != sb:
        return False
    if ya and yb and ya != yb:
        return False
    return bool(ta) and ta == tb


# ---- filename parsing (fallback for unscraped media) ----

SE_EP_RE = re.compile(r'[sS](\d{1,2})[eE](\d{1,3})\b')
CN_SEASON_EP_RE = re.compile(r'第([一二三四五六七八九十\d]+)季.*?第\s*(\d+)\s*集')
YEAR_TOKEN_RE = re.compile(r'^(?:19|20)\d{2}$')
RELEASE_JUNK_RE = re.compile(
    r'(?:720p|1080[pi]|2160p|4k|x264|x265|h\.?264|h\.?265|hevc|avc'
    r'|blu?ray|bdrip|brrip|web[\-.]?dl|webrip|web|hdtv|dvdrip|remux'
    r'|proper|repack|internal|limited|extended|complete|hdrip|amzn|nf|ddp?5?\.?\d?|10bit|8bit|hdr(?:10)?|dv)',
    re.I)


def _strip_extension(name):
    dot = name.rfind(".")
    if dot > 0:
        name = name[:dot]
    return name


def parse_filename(name):
    """Extract {title, year, season, episode} from a release filename.

    Rules applied in order: SxxExx markers, Chinese season/episode markers,
    a standalone (19|20)xx token as year (title stops there), then separator
    '.'/'_'/'-'/' ' -> space and best-effort release-tag stripping (residue
    like a lone 'DL' can survive in files without year or episode markers).
    Fields stay empty when nothing parses.
    """
    out = {"title": "", "year": "", "season": "", "episode": ""}
    name = _strip_extension((name or "").strip())
    if not name:
        return out

    m = SE_EP_RE.search(name)
    if m:
        out["season"], out["episode"] = m.group(1).lstrip("0") or "0", m.group(2).lstrip("0") or "0"
        name = name[:m.start()]
    else:
        m = CN_SEASON_EP_RE.search(name)
        if m:
            out["season"] = str(_season_number(m.group(1)) or "")
            out["episode"] = m.group(2).lstrip("0") or "0"
            name = name[:m.start()]

    tokens = re.split(r"[.\-_ ]+", name)
    for i, token in enumerate(tokens):
        if YEAR_TOKEN_RE.match(token):
            out["year"] = token
            tokens = tokens[:i]
            break
    out["title"] = " ".join(filter(None, (RELEASE_JUNK_RE.sub("", t) for t in tokens))).strip()
    return out
