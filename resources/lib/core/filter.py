# -*- coding: utf-8 -*-
"""Filter and rank subtitles according to user settings."""
from .http import noop_log
from .models import FORMATS, LANGS, SOURCES

_SOURCE_RANK = {s: i for i, s in enumerate(SOURCES)}  # SOURCES order is best-first


def sort_key(subtitle):
    """Simplified-Chinese bilingual first, then by source quality."""
    tags = subtitle.tags
    langs = set(tags.lang)
    if "chs" in langs and tags.bilingual:
        lang_tier = 0
    elif "chs" in langs:
        lang_tier = 1
    elif "cht" in langs and tags.bilingual:
        lang_tier = 2
    elif "cht" in langs:
        lang_tier = 3
    else:
        lang_tier = 4
    src_tier = min((_SOURCE_RANK.get(s, 5) for s in tags.source), default=5)
    return (lang_tier, src_tier)


def apply_filters(subtitles, settings, log=noop_log):
    """Drop subtitles disallowed by settings, then sort by preference.

    A missing tag list always passes its own filter (unknown source/format/lang
    is never hidden); 'bilingual' is the only hard filter.
    """
    if not subtitles:
        return []
    allowed_src = [k for k in SOURCES if settings.get(f"src_{k}")]
    allowed_lang = [k for k in LANGS if settings.get(f"lang_{k}")]
    allowed_fmt = [k for k in FORMATS if settings.get(f"fmt_{k}")]

    kept = []
    for s in subtitles:
        t = s.tags
        if settings.get("bilingual") and not t.bilingual:
            continue
        if allowed_src and t.source and not any(x in allowed_src for x in t.source):
            continue
        if allowed_lang and t.lang and not any(x in allowed_lang for x in t.lang):
            continue
        if allowed_fmt and t.fmt and not any(x in allowed_fmt for x in t.fmt):
            continue
        kept.append(s)

    log(f"filtered {len(kept)}/{len(subtitles)} subtitles")
    kept.sort(key=sort_key)
    return kept
