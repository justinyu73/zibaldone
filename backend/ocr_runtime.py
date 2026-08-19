"""First-use download of the OCR pack (RapidOCR + OpenCV + onnxruntime, built
from ocr_pack_main.py by the release workflow) so keyless local OCR stays
available without bloating the main installer by ~100MB.

Mirrors asr_runtime.py's trust pattern (.part streamed download → sha256 →
atomic extract → post-install selftest), with one deliberate difference: the
artifact is OUR build, published as a GitHub Release asset alongside each
version's installers. The expected sha256 therefore can't be pinned in source —
it is read from the release's own SHA256SUMS file (fetched over TLS from the
same release) before the archive is downloaded.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from ffmpeg_runtime import _os_key

_RELEASE_BASE = "https://github.com/justinyu73/zibaldone/releases/latest/download"

# ffmpeg_runtime._os_key() → (pack asset, SHA256SUMS asset that carries its hash)
_REGISTRY: dict[str, dict[str, str]] = {
    "win-64": {"asset": "ocr-pack-windows-x64.zip", "sums": "SHA256SUMS-windows-latest.txt"},
    "macos-64": {"asset": "ocr-pack-macos-arm64.zip", "sums": "SHA256SUMS-macos-latest.txt"},
    "linux-64": {"asset": "ocr-pack-linux-x64.zip", "sums": "SHA256SUMS-linux-latest.txt"},
}

_EXE = ".exe" if os.name == "nt" else ""
_STATE: dict[str, Any] = {}
_LOCK = threading.Lock()


def _root() -> Path:
    # Same tools tree as the other first-use runtimes.
    from services.readiness import _asr_root

    return _asr_root() / "tools" / "ocr-pack"


def pack_executable() -> str | None:
    """Resolved pack binary path, or None when the pack is not installed."""
    exe = _root() / "ocr-pack" / f"ocr-pack{_EXE}"
    return str(exe) if exe.is_file() else None


def status() -> dict[str, Any]:
    key = _os_key()
    progress = {k: _STATE.get(k) for k in ("status", "downloaded", "total", "error")}
    return {
        "supported": key in _REGISTRY,
        "os": key,
        "installed": pack_executable() is not None,
        "ready": pack_executable() is not None,
        "download": progress,
    }


def start_install() -> dict[str, Any]:
    key = _os_key()
    if key not in _REGISTRY:
        raise ValueError(f"此平台無對應的 OCR 引擎下載：{key}")
    with _LOCK:
        if _STATE.get("status") == "downloading":
            return {"status": "downloading"}
        _STATE.clear()
        _STATE.update({"status": "downloading", "downloaded": 0, "total": 0, "error": ""})
    threading.Thread(target=_install_worker, args=(key,), daemon=True).start()
    return {"status": "downloading"}


def _fetch_text(url: str) -> str:
    from radar import _ssl_context  # certifi context — packaged app has no system CA store

    request = urllib.request.Request(url, headers={"User-Agent": "yt-note-app"})
    with urllib.request.urlopen(request, timeout=60, context=_ssl_context()) as resp:
        return resp.read().decode("utf-8")


def _expected_sha256(sums_url: str, asset: str) -> str:
    """Parse the release's SHA256SUMS file for the pack asset's hash."""
    for line in _fetch_text(sums_url).splitlines():
        parts = line.replace("\\", "/").split()
        if len(parts) == 2 and parts[1].rsplit("/", 1)[-1] == asset:
            return parts[0].strip().lower()
    raise ValueError(f"release 的 SHA256SUMS 找不到 {asset} 的雜湊（此 release 可能未附 OCR 引擎包）")


def _install_worker(key: str) -> None:
    state = _STATE
    try:
        spec = _REGISTRY[key]
        expected = _expected_sha256(f"{_RELEASE_BASE}/{spec['sums']}", spec["asset"])

        root = _root()
        root.mkdir(parents=True, exist_ok=True)
        archive = root / "ocr-pack.zip"
        tmp_archive = archive.with_suffix(".zip.part")
        from radar import _ssl_context

        request = urllib.request.Request(f"{_RELEASE_BASE}/{spec['asset']}", headers={"User-Agent": "yt-note-app"})
        digest = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=120, context=_ssl_context()) as resp:
            state["total"] = int(resp.headers.get("Content-Length") or 0)
            state["downloaded"] = 0
            with open(tmp_archive, "wb") as handle:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    state["downloaded"] += len(chunk)
        if digest.hexdigest() != expected:
            tmp_archive.unlink(missing_ok=True)
            raise ValueError("OCR 引擎包下載檔 sha256 與 release 公佈不符（可能損毀或遭竄改），已捨棄")
        tmp_archive.replace(archive)

        final_dir = root / "ocr-pack"
        tmp_dir = root / "ocr-pack.part"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmp_dir)
        archive.unlink(missing_ok=True)
        # The zip holds the onedir as ocr-pack/…; land it atomically.
        inner = tmp_dir / "ocr-pack"
        if not inner.is_dir():
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise ValueError("OCR 引擎包內容不符預期（缺 ocr-pack 目錄）")
        if os.name != "nt":
            for entry in inner.rglob("*"):
                if entry.is_file():
                    entry.chmod(entry.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        shutil.rmtree(final_dir, ignore_errors=True)
        inner.replace(final_dir)
        shutil.rmtree(tmp_dir, ignore_errors=True)

        exe = pack_executable()
        if exe is None:
            raise ValueError("OCR 引擎包安裝後找不到執行檔")
        selftest = subprocess.run([exe, "selftest"], capture_output=True, text=True, timeout=180, check=False)
        if selftest.returncode != 0:
            tail = (selftest.stderr or selftest.stdout or f"exit {selftest.returncode}").strip()[-400:]
            raise ValueError(f"OCR 引擎包安裝後 selftest 失敗：{tail}")
        state["status"] = "done"
    except Exception as exc:  # noqa: BLE001 — surface to the UI, never crash the thread
        state["status"] = "error"
        state["error"] = str(exc)
