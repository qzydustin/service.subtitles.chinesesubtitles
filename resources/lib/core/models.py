# -*- coding: utf-8 -*-
"""Data models shared across the core library."""
from dataclasses import dataclass, field


@dataclass
class WorkQuery:
    """What the played file is: title plus optional season/episode/year."""
    title: str = ""      # search title (Kodi tvshow/title, manual input, filename parse)
    alt_titles: list = field(default_factory=list)  # fallbacks when title finds no works
    year: str = ""
    season: str = ""     # episodes only
    episode: str = ""
    is_tv: bool = False


@dataclass
class Work:
    """A work (movie or TV season) found on one or both subtitle sites."""
    title: str = ""          # site-original title, e.g. "绝命毒师 第二季 Breaking Bad"
    season: str = ""         # parsed from the title; "" when it carries none
    year: str = ""           # parsed from the title (Zimuku has it, SubHD doesn't)
    anchors: dict = field(default_factory=dict)
    # site name -> list of that site's page URLs for this work, e.g.
    # {"subhd": ["/d/3586996"], "zimuku": ["https://zimuku.org/subs/27187.html"]}
    # the keys double as coverage badges; duplicate pages of the same work
    # share one row


@dataclass
class Tags:
    """Parsed metadata of one subtitle entry."""
    lang: list = field(default_factory=list)    # chs / cht / eng
    fmt: list = field(default_factory=list)     # ass / srt / ssa / sub / sup / vtt
    source: list = field(default_factory=list)  # official / reprint / original / ai / machine
    bilingual: bool = False
    collection: bool = False
    fansub: str = ""
    production: str = ""                         # '剧集' or '电影'
    provider: str = ""                           # 'subhd' or 'zimuku'


@dataclass
class Subtitle:
    """One searchable subtitle entry."""
    filename: str
    link: str
    tags: Tags = field(default_factory=Tags)


@dataclass
class DownloadResult:
    """Outcome of a subtitle download."""
    status: str = "failed"  # 'ok', 'invalid' (not a subtitle) or 'failed'
    files: list = field(default_factory=list)
    display_names: list = field(default_factory=list)  # shortened names for pickers
    paths: list = field(default_factory=list)


SOURCE_LABELS = {"official": "官方", "reprint": "精修", "original": "原创", "ai": "AI", "machine": "机翻"}
FORMAT_LABELS = {"ass": "ASS", "srt": "SRT", "ssa": "SSA", "sub": "SUB", "sup": "SUP", "vtt": "VTT"}


def build_label(tags, filename=""):
    """Display label such as [电影][简英][官方][ASS][合集][YYeTs] name.srt."""
    label = ""
    if tags.production:
        label += f"[{tags.production}]"
    lang_marks = {"chs": "简", "cht": "繁", "eng": "英"}
    marks = "".join(lang_marks[x] for x in ("chs", "cht", "eng") if x in tags.lang)
    if marks:
        label += f"[{marks}]"
    for key, text in SOURCE_LABELS.items():
        if key in tags.source:
            label += f"[{text}]"
            break
    for key, text in FORMAT_LABELS.items():
        if key in tags.fmt:
            label += f"[{text}]"
            break
    if tags.collection:
        label += "[合集]"
    if tags.fansub:
        label += f"[{tags.fansub}]"
    if filename:
        label += f" {filename}"
    return label


def language_meta(tags):
    """(language_name, flag) pair for the Kodi listing."""
    if "eng" in tags.lang and "chs" not in tags.lang and "cht" not in tags.lang:
        return "English", "en"
    return "Chinese", "zh"
