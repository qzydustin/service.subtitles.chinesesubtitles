# -*- coding: utf-8 -*-
"""Title parsing and matching for aggregating works found on both sites."""
import re

CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_CN_DIGITS = "".join(CN_NUM)  # charset of a Chinese season count
_CN_SEASON = rf'第([{_CN_DIGITS}\d]+)\s*季'
_WORD_SEASON = r'season\s*(\d+)'
SEASON_RE = re.compile(f'{_CN_SEASON}|{_WORD_SEASON}', re.I)
_CENTURY = r'(?:19|20)\d{2}'
YEAR_RE = re.compile(rf'[（(]\s*({_CENTURY})\s*[)）]')

TITLE_STOPWORDS = {"the"}  # ignored when comparing site titles


def season_number(raw):
    """Chinese-numeral or digit season string -> int (0 when unparsable).
    Compounds through 九十九 parse: 十一 -> 11, 二十九 -> 29."""
    if raw.isdigit():
        return int(raw)
    tens, sep, ones = raw.partition("十")
    if not sep:
        return CN_NUM.get(raw, 0)
    if (not tens or tens in CN_NUM) and (not ones or ones in CN_NUM):
        return (CN_NUM[tens] if tens else 1) * 10 + (CN_NUM[ones] if ones else 0)
    return 0


def parse_meta(title):
    """Title -> (normalized token set, season str, year str)."""
    year = season = ""
    m = YEAR_RE.search(title)
    if m:
        year, title = m.group(1), YEAR_RE.sub(" ", title)
    m = SEASON_RE.search(title)
    if m:
        season = str(season_number(m.group(1) or m.group(2)))
        if season == "0":  # unparsable season counts (garbage, 百 and up) mean none
            season = ""
        title = SEASON_RE.sub(" ", title)
    tokens = set(re.sub(r"[^\w\s]", " ", title.lower()).split()) - TITLE_STOPWORDS
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

# trailing season marker in folder names: "电锯人 第一季", "Show Season 2", "Show S02"
FOLDER_SEASON_RE = re.compile(rf'(?:{_CN_SEASON}|{_WORD_SEASON}|S(\d{{1,2}}))\s*$', re.I)
SE_EP_RE = re.compile(r'[sS](\d{1,2})[.\s]*[eE](\d{1,3})\b')
EP_MARK_RE = re.compile(r'\b[eE][pP]?(\d{1,3})\b')  # lone episode: E05 / EP05
CN_EP_MARK_RE = re.compile(r'第\s*(\d{1,3})\s*[集话話]')
CN_SEASON_EP_RE = re.compile(rf'第([{_CN_DIGITS}\d]+)季.*?第\s*(\d+)\s*集')
YEAR_TOKEN_RE = re.compile(rf'^{_CENTURY}$')


def episode_marker(name):
    """(season, episode) ints carried by a filename; either may be None."""
    m = SE_EP_RE.search(name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = EP_MARK_RE.search(name)
    if m:
        return None, int(m.group(1))
    m = CN_EP_MARK_RE.search(name)
    if m:
        return None, int(m.group(1))
    return None, None

# release tags stripped from parsed titles, grouped by what they describe;
# the sub runs on tokens already split on . _ - space, so only dot-free
# spellings can occur (h264, never h.264)
JUNK_TAGS = {
    "resolution": ("720p", "1080p", "1080i", "2160p", "4k"),
    "codec": ("x264", "x265", "h264", "h265", "hevc", "avc"),
    "source": ("bluray", "bdrip", "brrip", "webdl", "webrip", "web",
               "hdtv", "dvdrip", "remux", "hdrip"),
    "platform": ("amzn", "nf"),
    "audio": ("dd", "ddp", "dd5", "dd51", "ddp5", "ddp51"),
    "edition": ("proper", "repack", "internal", "limited", "extended", "complete"),
    "range": ("8bit", "10bit", "hdr", "hdr10", "dv"),
}


def _any_of(tags):
    """Literal-tag alternation, longest first so 'webdl' is not
    half-stripped by 'web'."""
    return "|".join(re.escape(t) for t in sorted(tags, key=len, reverse=True))


RELEASE_JUNK_RE = re.compile(_any_of(sum(JUNK_TAGS.values(), ())), re.I)


def parse_filename(name):
    """Extract {title, year, season, episode} from a release filename.

    Rules applied in order: SxxExx markers, Chinese season/episode markers,
    a standalone (19|20)xx token as year (title stops there), then separator
    '.'/'_'/'-'/' ' -> space and best-effort release-tag stripping (residue
    like a lone 'DL' can survive in files without year or episode markers).
    Fields stay empty when nothing parses.
    """
    out = {"title": "", "year": "", "season": "", "episode": ""}
    name = (name or "").strip()
    dot = name.rfind(".")
    if dot > 0:
        name = name[:dot]
    if not name:
        return out

    m = SE_EP_RE.search(name)
    if m:
        out["season"], out["episode"] = m.group(1).lstrip("0") or "0", m.group(2).lstrip("0") or "0"
        name = name[:m.start()]
    else:
        m = CN_SEASON_EP_RE.search(name)
        if m:
            out["season"] = str(season_number(m.group(1)) or "")
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
