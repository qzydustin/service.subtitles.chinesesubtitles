# -*- coding: utf-8 -*-
"""Subtitle archive handling: zip natively (with GBK name recovery), others via backend."""
import os
import zipfile

from ._gbk_codec import fix_zip_filename
from .models import DownloadResult

SUBTITLE_EXTS = (".srt", ".sub", ".smi", ".ssa", ".ass", ".sup", ".vtt")
# vobsub index files ride along with their .sub (extracted but never
# returned as pickable subtitles)
SUBTITLE_SIDECAR_EXTS = (".idx",)
ARCHIVE_EXTS = (".zip", ".7z", ".tar", ".bz2", ".rar", ".gz", ".xz", ".iso", ".tgz", ".tbz2", ".cbr")


def extract(path, backend=None):
    """Extract an archive; return (target_dir, file_names).

    zip is handled natively; any other format is delegated to
    backend(path) when the host provides one (Kodi: vfs.rar / vfs.libarchive).
    """
    if path.lower().endswith(".zip"):
        return _extract_zip(path)
    if backend:
        try:
            return backend(path)
        except Exception:
            return "", []
    return "", []


def _extract_zip(path):
    """Extract subtitle entries from a zip, recovering GBK-mojibake filenames."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            entries, seen = [], set()
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # Without the UTF-8 flag zipfile decodes names as cp437
                name = info.filename if (info.flag_bits & 0x800) else fix_zip_filename(info.filename)
                name = os.path.basename(name)
                # entries are flattened to basenames: a same-named file in
                # another folder would overwrite the first, so keep only that
                if name in seen or not name.lower().endswith(
                        SUBTITLE_EXTS + SUBTITLE_SIDECAR_EXTS):
                    continue
                seen.add(name)
                entries.append((name, info))
            if not any(name.lower().endswith(SUBTITLE_EXTS) for name, _ in entries):
                return None, []  # sidecars alone are not a subtitle download
            target = path + "_extracted"
            os.makedirs(target, exist_ok=True)
            for name, info in entries:
                with zf.open(info) as src, open(os.path.join(target, name), "wb") as dst:
                    dst.write(src.read())
            return target, [name for name, _ in entries
                            if name.lower().endswith(SUBTITLE_EXTS)]
    except Exception:
        return None, []


def save_and_extract(dest, filename, data, backend=None):
    """Save downloaded bytes and extract when needed; never raises on bad content."""
    filename = os.path.basename(filename)
    path = os.path.join(dest, filename)
    with open(path, "wb") as f:
        f.write(data)
    if filename.lower().endswith(ARCHIVE_EXTS):
        target, files = extract(path, backend)
        if files:
            return DownloadResult("ok", files=files, display_names=shorten_names(files),
                                  paths=[os.path.join(target, f) for f in files])
    if filename.lower().endswith(SUBTITLE_EXTS):
        return DownloadResult("ok", files=[filename], display_names=[filename], paths=[path])
    return DownloadResult("invalid")


def shorten_names(names):
    """Trim the longest common prefix (up to a dot) so picker entries stay readable."""
    if len(names) < 2:
        return list(names)
    shortest = min(names, key=len)
    diff = next((i for i in range(len(shortest))
                 if any(n[i] != shortest[i] for n in names)), len(shortest))
    dot = shortest[:diff].rfind(".") + 1
    return [n[dot:] for n in names]
