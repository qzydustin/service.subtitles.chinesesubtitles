# -*- coding: utf-8 -*-
"""Subtitle archive handling: zip natively (with GBK name recovery), others via backend."""
import os
import zipfile

from ._gbk_codec import fix_zip_filename
from .models import DownloadResult

SUBTITLE_EXTS = (".srt", ".sub", ".smi", ".ssa", ".ass", ".sup", ".vtt")
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
            entries = []
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # Without the UTF-8 flag zipfile decodes names as cp437
                name = info.filename if (info.flag_bits & 0x800) else fix_zip_filename(info.filename)
                name = os.path.basename(name)
                if name.lower().endswith(SUBTITLE_EXTS):
                    entries.append((name, info))
            if not entries:
                return None, []
            target = path + "_extracted"
            os.makedirs(target, exist_ok=True)
            for name, info in entries:
                with zf.open(info) as src, open(os.path.join(target, name), "wb") as dst:
                    dst.write(src.read())
            return target, [name for name, _ in entries]
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
            return DownloadResult("ok", files, shorten_names(files),
                                  [os.path.join(target, f) for f in files])
    if filename.lower().endswith(SUBTITLE_EXTS):
        return DownloadResult("ok", [filename], [filename], [path])
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
