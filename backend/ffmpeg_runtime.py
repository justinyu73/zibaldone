"""First-use download of static ffmpeg + ffprobe so ASR/OCR work without the user
installing ffmpeg. Bundling (~40 MB each) would blow the release size budget, so we
fetch pinned, checksummed ffbinaries builds on demand — same .part → sha256 → atomic
pattern as the ASR models. Resolver prefers the downloaded copy, then env, then PATH.

macOS builds here are x86_64 (ffbinaries has no arm64); they run on Apple Silicon
via Rosetta 2, which is near-universal on M1/M2. If Rosetta is missing, exec fails
with a clear error the caller surfaces.
"""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

_FFBIN = "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v6.1"

# Per-OS pinned static builds. sha256 filled from the downloaded artifacts.
_REGISTRY: dict[str, dict[str, dict[str, str]]] = {
    "linux-64": {
        "ffmpeg": {"url": f"{_FFBIN}/ffmpeg-6.1-linux-64.zip", "sha256": "8bb4a27f5fd02f3dd9a5e75c9eddf6ace1d50a08929ee0d20bbf17eb467fb711"},
        "ffprobe": {"url": f"{_FFBIN}/ffprobe-6.1-linux-64.zip", "sha256": "cb690c360042b51d9e901db2b0185c585330c1067b5c5edf0b6a5e26e0375e2a"},
    },
    "macos-64": {
        "ffmpeg": {"url": f"{_FFBIN}/ffmpeg-6.1-macos-64.zip", "sha256": "ffcd56ce5ef50c4d36d675b0ee80674f5a0869f94746460ff5d058a33cbd3128"},
        "ffprobe": {"url": f"{_FFBIN}/ffprobe-6.1-macos-64.zip", "sha256": "878ab8787ca6c48a11cb668c01d544be4c1bf655637d719cdf3b3179841545f2"},
    },
    "win-64": {
        "ffmpeg": {"url": f"{_FFBIN}/ffmpeg-6.1-win-64.zip", "sha256": "b0fb4bcef9d4b5f7a77d2e4854f80d4ce3e43809bc29fd1f97caa1b467f96993"},
        "ffprobe": {"url": f"{_FFBIN}/ffprobe-6.1-win-64.zip", "sha256": "3c0ea2856cf65edff23a2d4e76b1ceabba65fe8b1bed684ee2eeba24aa9427c3"},
    },
}
_EXE = ".exe" if os.name == "nt" else ""
_TOOLS = ("ffmpeg", "ffprobe")
_DOWNLOADS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _root() -> Path:
    # Same tools tree as whisper.cpp (services.readiness._asr_root/tools/…).
    from services.readiness import _asr_root

    return _asr_root() / "tools" / "ffmpeg"


def _os_key() -> str:
    if os.name == "nt":
        return "win-64"
    if platform.system() == "Darwin":
        return "macos-64"
    return "linux-64"


def _installed_path(tool: str) -> Path:
    return _root() / f"{tool}{_EXE}"


def resolve(tool: str) -> str:
    """downloaded copy → {FFMPEG,FFPROBE}_BINARY env → PATH."""
    path = _installed_path(tool)
    if path.is_file() and os.access(path, os.X_OK):
        return str(path)
    override = os.getenv(f"{tool.upper()}_BINARY", "").strip()
    if override:
        return override
    return shutil.which(tool) or ""


def status() -> dict[str, Any]:
    key = _os_key()
    progress = {t: {k: _DOWNLOADS.get(t, {}).get(k) for k in ("status", "downloaded", "total", "error")} for t in _TOOLS}
    return {
        "supported": key in _REGISTRY,
        "os": key,
        "ffmpeg_resolved": bool(resolve("ffmpeg")),
        "ffprobe_resolved": bool(resolve("ffprobe")),
        "ready": bool(resolve("ffmpeg") and resolve("ffprobe")),
        "download": progress,
    }


def start_install() -> dict[str, Any]:
    key = _os_key()
    if key not in _REGISTRY:
        raise ValueError(f"此平台無對應的 ffmpeg 下載：{key}")
    with _LOCK:
        if any(_DOWNLOADS.get(t, {}).get("status") == "downloading" for t in _TOOLS):
            return {"status": "downloading"}
        for tool in _TOOLS:
            _DOWNLOADS[tool] = {"status": "downloading", "downloaded": 0, "total": 0, "error": ""}
    threading.Thread(target=_install_worker, args=(key,), daemon=True).start()
    return {"status": "downloading"}


def _install_worker(key: str) -> None:
    for tool in _TOOLS:
        spec = _REGISTRY[key][tool]
        state = _DOWNLOADS[tool]
        try:
            _download_and_extract(tool, spec["url"], spec["sha256"], state)
            state["status"] = "done"
        except Exception as exc:  # noqa: BLE001 — surface to the UI, never crash the thread
            state["status"] = "error"
            state["error"] = str(exc)
            return


def _download_and_extract(tool: str, url: str, sha256: str, state: dict[str, Any]) -> None:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    tmp_zip = root / f"{tool}.zip.part"
    request = urllib.request.Request(url, headers={"User-Agent": "yt-note-app"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as resp:
        state["total"] = int(resp.headers.get("Content-Length") or 0)
        with open(tmp_zip, "wb") as handle:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                state["downloaded"] += len(chunk)
    if digest.hexdigest() != sha256:
        tmp_zip.unlink(missing_ok=True)
        raise ValueError(f"{tool} 下載檔 sha256 不符（可能損毀），已捨棄")
    dest = _installed_path(tool)
    tmp_bin = dest.with_suffix(dest.suffix + ".part")
    with zipfile.ZipFile(tmp_zip) as archive:
        member = next(n for n in archive.namelist() if Path(n).name.lower() in (tool, f"{tool}.exe"))
        with archive.open(member) as src, open(tmp_bin, "wb") as out:
            shutil.copyfileobj(src, out)
    tmp_zip.unlink(missing_ok=True)
    tmp_bin.chmod(tmp_bin.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    tmp_bin.replace(dest)
