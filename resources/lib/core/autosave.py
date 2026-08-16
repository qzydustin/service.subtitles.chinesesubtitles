# -*- coding: utf-8 -*-
"""Naming downloaded subtitles after their videos so Kodi auto-loads them."""
import re

VIDEO_EXTS = (".mkv", ".mp4", ".avi", ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts",
              ".mts", ".flv", ".webm", ".mov", ".iso", ".vob", ".rmvb", ".strm")

SE_EP_MARK_RE = re.compile(r'[sS](\d{1,2})\s*[eE](\d{1,3})\b')
EP_MARK_RE = re.compile(r'\b[eE][pP]?(\d{1,3})\b')
CN_EP_MARK_RE = re.compile(r'第\s*(\d{1,3})\s*[集话話]')
_LANG_CODE = r'(?:chs|cht|chi|eng|zho|jpn|kor|sc|tc)'
LANG_TAG_RE = re.compile(r'(?:^|[.\-_ ])(' + _LANG_CODE + r'(?:[&+]' + _LANG_CODE + r')*)'
                         r'(?![a-z0-9])', re.I)
CN_LANG_TAG_RE = re.compile(r'简体|繁体|繁體|简英|繁英|中英|双语|简|繁')


def episode_marker(name):
    """(season, episode) ints carried by a filename; either may be None."""
    m = SE_EP_MARK_RE.search(name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = EP_MARK_RE.search(name)
    if m:
        return None, int(m.group(1))
    m = CN_EP_MARK_RE.search(name)
    if m:
        return None, int(m.group(1))
    return None, None


def lang_tag(name):
    """Distinguishing language tag of a subtitle twin ('chs', '简体', ...)."""
    m = LANG_TAG_RE.search(name)
    if m:
        return m.group(1).lower()
    m = CN_LANG_TAG_RE.search(name)
    return m.group(0) if m else ""


LANG_HINTS = {"chs": ("chs", "简体", "简", "sc"), "cht": ("cht", "繁體", "繁体", "tc", "繁"),
              "eng": ("eng",)}


def _tagged_stem(stem, name, used):
    tag = lang_tag(name)
    new = f"{stem}.{tag}" if tag else stem
    if new in used:
        n = 2
        while f"{new}.{n}" in used:
            n += 1
        new = f"{new}.{n}"
    return new


def rename_map(sub_names, video_stem, sibling_stems, season=None):
    """Map each subtitle filename to the stem it should be saved under.

    A single subtitle goes to the playing video's stem. A marker-less video
    with unmarked files (movie twins) maps everything to that stem. In a
    pack, each episode-marked subtitle goes to the video carrying the same
    episode (season preferred when known); unmarked pack entries are left
    out for the manual pick. A language tag always survives the rename
    (Video.chs.ass / Video.cht.ass never overwrite each other across
    downloads); leftover collisions get a numeric tail.
    """
    if len(sub_names) <= 1:
        if not sub_names:
            return {}
        return {sub_names[0]: _tagged_stem(video_stem, sub_names[0], set())}
    if episode_marker(video_stem)[1] is None and \
            all(episode_marker(n)[1] is None for n in sub_names):
        mapping, used = {}, set()
        for name in sub_names:
            mapping[name] = _tagged_stem(video_stem, name, used)
            used.add(mapping[name])
        return mapping
    candidates = {}  # episode -> [(season, stem)] with the playing video first
    for stem in [video_stem] + [s for s in sibling_stems if s != video_stem]:
        s, e = episode_marker(stem)
        if e is not None:
            candidates.setdefault(e, []).append((s, stem))
    mapping, used = {}, set()
    for name in sub_names:
        s, e = episode_marker(name)
        if e is None or e not in candidates:
            continue
        pool = candidates[e]
        stem = next((st for sv, st in pool if s is not None and sv == s),
                    next((st for sv, st in pool if sv == season), pool[0][1]))
        mapping[name] = _tagged_stem(stem, name, used)
        used.add(mapping[name])
    return mapping


def playback_pick(mapping, video_stem, preferred=("chs", "cht", "eng")):
    """The downloaded file to load right now: among the entries saved under
    the playing video's stem, the first language match in `preferred`
    order (falling back to the first entry). '' when nothing maps to the
    playing video."""
    candidates = [name for name, stem in mapping.items()
                  if stem == video_stem or stem.startswith(video_stem + ".")]
    if not candidates:
        return ""
    for lang in preferred:
        for name in candidates:
            if any(h in name.lower() for h in LANG_HINTS.get(lang, ())):
                return name
    return candidates[0]
