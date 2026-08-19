"""First-use download of a prebuilt whisper.cpp CLI + ggml-base model so local
ASR works without the user building whisper.cpp from source (impossible on a
stock Windows machine). Same .part → checksum → atomic pattern as
ffmpeg_runtime / the ASR model downloads. Writes the runtime-lock.json that
services.readiness._local_asr_runtime_readiness verifies.

Prebuilt archives come from the official ggml-org/whisper.cpp GitHub release
(pinned version + sha256). Windows ships whisper-cli.exe + ggml DLLs; Linux
ships whisper-cli + lib*.so with an $ORIGIN rpath — both run straight from the
bin dir. macOS has no prebuilt CLI asset upstream, so it keeps the source-build
path (setup_asr_runtime.sh).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

_VERSION = "v1.9.2"
_RELEASE = f"https://github.com/ggml-org/whisper.cpp/releases/download/{_VERSION}"

# Per-OS pinned prebuilt archives. sha256 computed from the release assets.
_REGISTRY: dict[str, dict[str, str]] = {
    "win-64": {
        "url": f"{_RELEASE}/whisper-bin-x64.zip",
        "sha256": "49dcc16de826f20bd53d44f947a1ae49dfa81f86cad67a64d80820cb192d674a",
        "archive": "zip",
    },
    "linux-64": {
        "url": f"{_RELEASE}/whisper-bin-ubuntu-x64.tar.gz",
        "sha256": "46811a3ecf584307480a220b9ef5ff81b7b22dc41577cbc274ce3afc61f753b1",
        "archive": "tar.gz",
    },
}

_MODEL_NAME = "ggml-base.bin"
_MODEL_URL = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{_MODEL_NAME}"
_MODEL_OFFICIAL_SHA1 = "465707469ff3a37a2b9b8d8f89f2f99de7299dac"  # whisper.cpp models/README.md (base)

_EXE = ".exe" if os.name == "nt" else ""
_DOWNLOAD: dict[str, Any] = {}
_LOCK = threading.Lock()


def _root() -> Path:
    # Same tools tree as ffmpeg (services.readiness._asr_root/tools/…).
    from services.readiness import _asr_root

    return _asr_root() / "tools" / "whisper.cpp"


def _bin_dir() -> Path:
    return _root() / "bin"


def _binary_path() -> Path:
    return _bin_dir() / f"whisper-cli{_EXE}"


def _model_path() -> Path:
    return _root() / "models" / _MODEL_NAME


def _lock_path() -> Path:
    return _root() / "runtime-lock.json"


def _os_key() -> str:
    if os.name == "nt":
        return "win-64"
    if platform.system() == "Darwin":
        return "macos"
    return "linux-64"


def status() -> dict[str, Any]:
    from services.readiness import _local_asr_runtime_readiness

    key = _os_key()
    readiness = _local_asr_runtime_readiness()
    return {
        "supported": key in _REGISTRY,
        "os": key,
        "runtime_ready": readiness.get("runtime_ready") is True,
        "readiness": readiness,
        "download": {k: _DOWNLOAD.get(k) for k in ("status", "downloaded", "total", "error", "stage")},
    }


def start_install() -> dict[str, Any]:
    key = _os_key()
    if key not in _REGISTRY:
        raise ValueError(f"此平台無預建 whisper.cpp 下載（{key}）——請跑 backend/setup_asr_runtime.sh 從原始碼建置")
    with _LOCK:
        if _DOWNLOAD.get("status") == "downloading":
            return {"status": "downloading"}
        _DOWNLOAD.update({"status": "downloading", "downloaded": 0, "total": 0, "error": "", "stage": "binary"})
    threading.Thread(target=_install_worker, args=(key,), daemon=True).start()
    return {"status": "downloading"}


def _install_worker(key: str) -> None:
    try:
        _install_binary(_REGISTRY[key])
        _DOWNLOAD["stage"] = "model"
        _DOWNLOAD["downloaded"] = 0
        _DOWNLOAD["total"] = 0
        _install_model()
        _write_lock()
        _DOWNLOAD["status"] = "done"
    except Exception as exc:  # noqa: BLE001 — surface to the UI, never crash the thread
        _DOWNLOAD["status"] = "error"
        _DOWNLOAD["error"] = str(exc)


def _download_file(url: str, dest: Path, digest_name: str) -> str:
    """Stream url to dest (.part handled by caller), returning the hex digest."""
    request = urllib.request.Request(url, headers={"User-Agent": "yt-note-app"})
    digest = hashlib.new(digest_name)
    with urllib.request.urlopen(request, timeout=60) as resp:
        _DOWNLOAD["total"] = int(resp.headers.get("Content-Length") or 0)
        with open(dest, "wb") as handle:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                _DOWNLOAD["downloaded"] += len(chunk)
    return digest.hexdigest()


def _wanted_member(name: str) -> str:
    """Archive member → target basename, or '' to skip. Keeps only the CLI and
    its shared libraries (test/server/bench binaries stay out)."""
    base = Path(name).name
    if base == f"whisper-cli{_EXE}":
        return base
    if base.endswith(".dll") or (base.startswith("lib") and ".so" in base):
        return base
    return ""


def _install_binary(spec: dict[str, str]) -> None:
    bin_dir = _bin_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="whisper_runtime_"))
    archive = tmp / f"archive.{spec['archive']}"
    try:
        if _download_file(spec["url"], archive, "sha256") != spec["sha256"]:
            raise ValueError("whisper.cpp 下載檔 sha256 不符（可能損毀），已捨棄")
        extracted: list[Path] = []
        if spec["archive"] == "zip":
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.namelist():
                    target = _wanted_member(member)
                    if target:
                        with bundle.open(member) as src, open(bin_dir / target, "wb") as out:
                            shutil.copyfileobj(src, out)
                        extracted.append(bin_dir / target)
        else:
            with tarfile.open(archive) as bundle:
                for member in bundle.getmembers():
                    if not member.isfile():
                        continue
                    target = _wanted_member(member.name)
                    if target:
                        src = bundle.extractfile(member)
                        with open(bin_dir / target, "wb") as out:
                            shutil.copyfileobj(src, out)  # type: ignore[arg-type]
                        extracted.append(bin_dir / target)
        binary = _binary_path()
        if not binary.is_file():
            raise ValueError("解壓後找不到 whisper-cli——預建包內容可能已變更")
        for path in extracted:
            path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _install_model() -> None:
    dest = _model_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        if _download_file(_MODEL_URL, tmp, "sha1") != _MODEL_OFFICIAL_SHA1:
            raise ValueError("模型檔 sha1 與官方公佈不符（可能損毀），已捨棄")
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _write_lock() -> None:
    binary = _binary_path()
    model = _model_path()
    try:
        help_run = subprocess.run([binary.as_posix(), "--help"], capture_output=True, timeout=30, check=False)
        help_exit = help_run.returncode
    except OSError as exc:
        raise ValueError(f"whisper-cli 無法執行（{exc}）——此 CPU 可能不支援預建二進位") from exc
    lock = {
        "runtime_name": "whisper.cpp",
        "runtime_version": _VERSION,
        "build": {
            "build_ok": True,
            "binary_path": f"tools/whisper.cpp/bin/whisper-cli{_EXE}",
            "binary_bytes": binary.stat().st_size,
            "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "help_exit_code": help_exit,
        },
        "model": {
            "path": f"tools/whisper.cpp/models/{_MODEL_NAME}",
            "bytes": model.stat().st_size,
            "sha1": hashlib.sha1(model.read_bytes()).hexdigest(),
            "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
            "official_sha1_expected": _MODEL_OFFICIAL_SHA1,
            "official_sha1_verified": True,
        },
    }
    _lock_path().write_text(json.dumps(lock, indent=2), encoding="utf-8")
