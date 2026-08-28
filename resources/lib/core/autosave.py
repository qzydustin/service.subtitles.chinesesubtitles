# -*- coding: utf-8 -*-
"""Naming downloaded subtitles after their videos so Kodi auto-loads them."""
import re

from .matcher import episode_marker

VIDEO_EXTS = (".mkv", ".mp4", ".avi", ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts",
              ".mts", ".flv", ".webm", ".mov", ".iso", ".vob", ".rmvb", ".strm")

_LANG_CODE = r'(?:chs|cht|chi|eng|zho|jpn|kor|sc|tc)'
LANG_TAG_RE = re.compile(r'(?:^|[.\-_ ])(' + _LANG_CODE + r'(?:[&+]' + _LANG_CODE + r')*)'
                         r'(?![a-z0-9])', re.I)
CN_LANG_TAG_RE = re.compile(r'简体|繁体|繁體|简英|繁英|中英|双语|简|繁')


def lang_tag(name):
    """Distinguishing language tag of a subtitle twin ('chs', '简体', ...)."""
    m = LANG_TAG_RE.search(name)
    if m:
        return m.group(1).lower()
    m = CN_LANG_TAG_RE.search(name)
    return m.group(0) if m else ""


LANG_HINTS = {"chs": ("chs", "简体", "简", "sc"), "cht": ("cht", "繁體", "繁体", "tc", "繁"),
              "eng": ("eng",)}

_CH_CODE = r'(?:chs|cht|chi|zho|sc|tc)'
BILINGUAL_RE = re.compile(
    r'双语|(?:中|[简繁][体體]?)\s*[&+]?\s*英'
    r'|(?:^|[.\-_ ])' + _CH_CODE + r'[&+.\-_ ]eng(?![a-z0-9])'
    r'|(?:^|[.\-_ ])eng[&+.\-_ ]' + _CH_CODE + r'(?![a-z0-9])', re.I)


def is_bilingual(name):
    """Whether a filename marks a Chinese+English twin (chs&eng, 简英, 双语...)."""
    return bool(BILINGUAL_RE.search(name))


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


def variant_rank(name, preferred=("chs", "cht", "eng")):
    """Sort key among language twins: earliest `preferred` language first,
    a bilingual name beating a single-language one at the same rank
    (mirroring the search listing's bilingual-first sort)."""
    low = name.lower()
    tier = next((i for i, lang in enumerate(preferred)
                 if any(h in low for h in LANG_HINTS.get(lang, ()))), len(preferred))
    return (tier, 0 if is_bilingual(name) else 1)


def playback_candidates(mapping, video_stem, preferred=("chs", "cht", "eng")):
    """The entries saved under the playing video's stem, best variant first.
    The caller loads the first — or asks the user when several compete.
    Empty when nothing maps to the playing video."""
    candidates = [name for name, stem in mapping.items()
                  if stem == video_stem or stem.startswith(video_stem + ".")]
    return sorted(candidates, key=lambda n: variant_rank(n, preferred))


def playback_pick(mapping, video_stem, preferred=("chs", "cht", "eng")):
    """The single best file to load right now; '' when nothing maps."""
    candidates = playback_candidates(mapping, video_stem, preferred)
    return candidates[0] if candidates else ""


def fanout_names(mapping, picked, video_stem="", preferred=("chs", "cht", "eng")):
    """Trim a pack's rename map to what should be copied out once `picked`
    loads: one file per remaining video — the picked file's language variant
    when that video has one, else the video's best variant — keeping the
    fan-out folders to a single twin. Everything mapped to the playing
    video's stem is excluded (the player stores the pick)."""
    tag = lang_tag(picked)
    groups = {}
    for name, stem in mapping.items():
        if name == picked or (video_stem and
                              (stem == video_stem or stem.startswith(video_stem + "."))):
            continue
        groups.setdefault(episode_marker(name), []).append(name)
    return [min([n for n in names if lang_tag(n) == tag] or names,
                key=lambda n: variant_rank(n, preferred))
            for names in groups.values()]
