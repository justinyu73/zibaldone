"""First-use download of a precompiled whisper.cpp ASR runtime (whisper-cli +
its sibling shared libs) plus the base ASR model, so video/meeting ASR works
without the setup_asr_runtime.sh build toolchain (git/cmake/make/cc/g++).

Mirrors ffmpeg_runtime.py's per-OS pinned + checksummed first-run download
(.part → sha256 → atomic install). One deliberate shape difference: ffmpeg's
release is a single static binary per zip, cherry-picked by member name;
whisper.cpp's official release is a *dynamically linked* build — whisper-cli
plus ggml/whisper shared libs (and, on Windows, per-CPU-microarchitecture
ggml-cpu-*.dll variants ggml picks between at runtime) that must all sit next
to the binary. So this module extracts the whole (checksum-verified) archive,
same as local_llm_builtin.py already does for the sibling llama.cpp runtime,
then locates whisper-cli within the extracted tree and records its resolved
path — verified empirically this session (2026-08-14): the downloaded Linux
build's whisper-cli finds its sibling .so files via a same-directory rpath
with no LD_LIBRARY_PATH needed, and standard Windows DLL search order checks
the launched exe's own directory first, so no PATH/env plumbing is needed on
either platform as long as the files stay together (which extracting the
whole archive into one directory guarantees).

Writes services.readiness._local_asr_runtime_readiness()'s existing
runtime-lock.json contract directly, so readiness.py and its callers
(whisper_transcribe.py, routers/readiness.py) need no changes.

Pinned to a specific ggml-org/whisper.cpp release tag (not "latest") — same
convention as local_llm_builtin.py's _LLAMA_RELEASE: upgrading means bumping
the tag here and re-verifying (re-download + re-hash) before shipping.

macOS: ggml-org/whisper.cpp ships no precompiled CLI binary for macOS —
checked this session against both the latest release (v1.9.2) and an older
one (v1.7.5) via the GitHub releases API: assets are Windows (Win32/x64,
CPU/BLAS/CUDA variants) + Ubuntu (x64/arm64) + an xcframework for Swift/ObjC
app embedding only, never a macOS command-line executable. _REGISTRY has no
"macos-64" entry, so status() reports supported=False there (same shape as
an unsupported ffmpeg_runtime.py platform) and macOS keeps using
setup_asr_runtime.sh (build from source) — there is no real precompiled
artifact to fetch, so this module does not pretend otherwise.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from ffmpeg_runtime import _os_key

# Pinned release (ggml-org/whisper.cpp). sha256 of each whole archive verified
# this session by downloading the real artifact and hashing it — see
# docs/evidence/2026-08-14-win-asr-ocr-hardsub-acceptance.md for provenance.
_RELEASE = "v1.9.2"
_BASE = f"https://github.com/ggml-org/whisper.cpp/releases/download/{_RELEASE}"

_REGISTRY: dict[str, dict[str, str]] = {
    "win-64": {
        "url": f"{_BASE}/whisper-bin-x64.zip",
        "sha256": "49dcc16de826f20bd53d44f947a1ae49dfa81f86cad67a64d80820cb192d674a",
    },
    "linux-64": {
        "url": f"{_BASE}/whisper-bin-ubuntu-x64.tar.gz",
        "sha256": "46811a3ecf584307480a220b9ef5ff81b7b22dc41577cbc274ce3afc61f753b1",
    },
    # macos-64: intentionally absent — see module docstring.
}

# Same base model + official sha1 setup_asr_runtime.sh already pins
# (whisper.cpp models/README.md), downloadable here too so the app-internal
# path doesn't depend on that dev script.
_MODEL_NAME = "ggml-base.bin"
_MODEL_URL = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{_MODEL_NAME}"
_MODEL_SHA1 = "465707469ff3a37a2b9b8d8f89f2f99de7299dac"

_EXE = ".exe" if os.name == "nt" else ""
_STATE: dict[str, Any] = {}
_LOCK = threading.Lock()


def _root() -> Path:
    # Same tools tree services.readiness._local_asr_runtime_readiness() reads.
    from services.readiness import _asr_root

    return _asr_root() / "tools" / "whisper.cpp"


def _bin_dir() -> Path:
    return _root() / "bin"


def _model_path() -> Path:
    return _root() / "models" / _MODEL_NAME


def _lock_path() -> Path:
    return _root() / "runtime-lock.json"


def _find_binary(base: Path) -> Path | None:
    if not base.is_dir():
        return None
    hits = sorted(base.rglob(f"whisper-cli{_EXE}"))
    return hits[0] if hits else None


def status() -> dict[str, Any]:
    key = _os_key()
    binary = _find_binary(_bin_dir())
    model = _model_path()
    progress = {k: _STATE.get(k) for k in ("status", "stage", "downloaded", "total", "error")}
    return {
        "supported": key in _REGISTRY,
        "os": key,
        "binary_installed": binary is not None,
        "model_installed": model.is_file(),
        "ready": binary is not None and model.is_file() and _lock_path().is_file(),
        "download": progress,
    }


def start_install() -> dict[str, Any]:
    key = _os_key()
    if key not in _REGISTRY:
        raise ValueError(
            f"此平台無對應的語音轉錄執行檔下載：{key}（開發環境可改用 backend/setup_asr_runtime.sh 從原始碼建置）"
        )
    with _LOCK:
        if _STATE.get("status") == "downloading":
            return {"status": "downloading"}
        _STATE.clear()
        _STATE.update({"status": "downloading", "stage": "binary", "downloaded": 0, "total": 0, "error": ""})
    threading.Thread(target=_install_worker, args=(key,), daemon=True).start()
    return {"status": "downloading"}


def _stream_download(url: str, dest: Path, state: dict[str, Any]) -> None:
    """.part streamed download so a half-download never looks installed."""
    from radar import _ssl_context  # certifi context — packaged app has no system CA store

    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "yt-note-app"})
    with urllib.request.urlopen(request, timeout=120, context=_ssl_context()) as resp:
        state["total"] = int(resp.headers.get("Content-Length") or 0)
        state["downloaded"] = 0
        with open(dest, "wb") as handle:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                state["downloaded"] += len(chunk)


def _stream_hash(path: Path, *algos: str) -> dict[str, str]:
    digests = {name: hashlib.new(name) for name in algos}
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            for digest in digests.values():
                digest.update(chunk)
    return {name: digest.hexdigest() for name, digest in digests.items()}


def _install_binary(key: str, state: dict[str, Any]) -> dict[str, Any]:
    spec = _REGISTRY[key]
    root = _root()
    archive = root / ("archive.zip" if spec["url"].endswith(".zip") else "archive.tar.gz")
    tmp_archive = archive.with_suffix(archive.suffix + ".part")
    _stream_download(spec["url"], tmp_archive, state)
    archive_hash = _stream_hash(tmp_archive, "sha256")["sha256"]
    if archive_hash != spec["sha256"]:
        tmp_archive.unlink(missing_ok=True)
        raise ValueError("whisper.cpp 執行檔下載檔 sha256 不符（可能損毀或遭竄改），已捨棄")
    tmp_archive.replace(archive)

    bin_dir = _bin_dir()
    tmp_bin_dir = bin_dir.with_name(bin_dir.name + ".part")
    shutil.rmtree(tmp_bin_dir, ignore_errors=True)
    tmp_bin_dir.mkdir(parents=True, exist_ok=True)
    try:
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(tmp_bin_dir)
        else:
            with tarfile.open(archive) as tf:
                tf.extractall(tmp_bin_dir, filter="data")
    finally:
        archive.unlink(missing_ok=True)

    binary = _find_binary(tmp_bin_dir)
    if binary is None:
        shutil.rmtree(tmp_bin_dir, ignore_errors=True)
        raise ValueError(f"whisper.cpp 執行檔解壓完成但找不到 whisper-cli{_EXE}")
    if os.name != "nt":
        for entry in tmp_bin_dir.rglob("*"):
            if entry.is_file():
                entry.chmod(entry.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    shutil.rmtree(bin_dir, ignore_errors=True)
    tmp_bin_dir.replace(bin_dir)
    binary = _find_binary(bin_dir)  # re-resolve under the now-final bin_dir path
    if binary is None:
        raise ValueError("whisper.cpp 執行檔安裝後遺失")

    help_run = subprocess.run([str(binary), "--help"], capture_output=True, text=True, timeout=20, check=False)
    if help_run.returncode != 0:
        tail = (help_run.stderr or help_run.stdout or f"exit {help_run.returncode}").strip()[-400:]
        raise ValueError(f"whisper.cpp 執行檔安裝後無法執行：{tail}")

    binary_hash = _stream_hash(binary, "sha256")["sha256"]
    return {
        "build_ok": True,
        "binary_path": binary.as_posix(),
        "binary_bytes": binary.stat().st_size,
        "binary_sha256": binary_hash,
        "help_exit_code": help_run.returncode,
    }


def _install_model(state: dict[str, Any]) -> dict[str, Any]:
    dest = _model_path()
    if not (dest.is_file() and _stream_hash(dest, "sha1")["sha1"] == _MODEL_SHA1):
        tmp = dest.with_suffix(dest.suffix + ".part")
        _stream_download(_MODEL_URL, tmp, state)
        digest = _stream_hash(tmp, "sha1")["sha1"]
        if digest != _MODEL_SHA1:
            tmp.unlink(missing_ok=True)
            raise ValueError("ASR 模型下載檔 sha1 不符官方值（可能損毀或遭竄改），已捨棄")
        tmp.replace(dest)
    hashes = _stream_hash(dest, "sha1", "sha256")
    return {
        "path": dest.as_posix(),
        "bytes": dest.stat().st_size,
        "sha1": hashes["sha1"],
        "sha256": hashes["sha256"],
        "official_sha1_expected": _MODEL_SHA1,
        "official_sha1_verified": True,
    }


def _install_worker(key: str) -> None:
    state = _STATE
    try:
        state["stage"] = "binary"
        build = _install_binary(key, state)
        state["stage"] = "model"
        state["downloaded"] = 0
        state["total"] = 0
        model = _install_model(state)
        _lock_path().write_text(
            json.dumps(
                {
                    "runtime_name": "whisper.cpp",
                    "runtime_version": _RELEASE,
                    "build": build,
                    "model": model,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        state["status"] = "done"
    except Exception as exc:  # noqa: BLE001 — surface to the UI, never crash the thread
        state["status"] = "error"
        state["error"] = str(exc)
