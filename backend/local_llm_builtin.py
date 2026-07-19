"""內建本機 LLM runtime（llama.cpp llama-server）＋首用下載（spec C）。

乾淨機器免裝任何外部工具，裝好即為預設本機翻譯/摘要模型，離線、免金鑰。
runtime binary（10-17MB）與模型 gguf（~2.4GB）都不進安裝包（85.8MB budget，
spike 2026-07-05：打包會推到 96-104MB 跨 warn 線）→ 全部首用下載。
下載沿用 ASR model 的 .part+原子搬移＋background+poll+lock 範式（不平行造）。
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import tarfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

# pinned release（固定模式：不追 latest；升級=改版號+實測）。CPU/Metal 通用建置，
# 刻意不用 CUDA/ROCm 大包（250-370MB，且多數機器不適用）。
_LLAMA_RELEASE = "b9873"
_RUNTIME_ASSETS = {
    ("darwin", "arm64"): f"llama-{_LLAMA_RELEASE}-bin-macos-arm64.tar.gz",
    ("windows", "amd64"): f"llama-{_LLAMA_RELEASE}-bin-win-cpu-x64.zip",
    ("linux", "x86_64"): f"llama-{_LLAMA_RELEASE}-bin-ubuntu-x64.tar.gz",
}
_RUNTIME_URL_BASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{_LLAMA_RELEASE}"

# 模型與 A 的推薦一致（gemma3:4b），Q4_K_M＝品質/大小平衡的社群慣用量化。
MODEL_URL = "https://huggingface.co/ggml-org/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q4_K_M.gguf"
MODEL_FILENAME = "gemma-3-4b-it-Q4_K_M.gguf"
MODEL_ID = "llamacpp:gemma-3-4b-it"
MODEL_LABEL = "gemma3:4b（內建本機）"

_PORT = int(os.getenv("YT_NOTE_LLAMACPP_PORT", "8767"))
_SPAWN_WAIT_SECONDS = 60

_DOWNLOADS: dict[str, dict[str, Any]] = {}
_DOWNLOAD_LOCK = threading.Lock()
_SERVER_LOCK = threading.Lock()
_SERVER_PROC: subprocess.Popen | None = None


def _root() -> Path:
    base = Path(os.getenv("YT_NOTE_ASR_ROOT", str(Path.home() / ".config" / "yt-note-app")))
    return base / "llama_runtime"


def runtime_asset_name() -> str | None:
    key = (platform.system().lower(), platform.machine().lower())
    return _RUNTIME_ASSETS.get(key)


def _server_binary() -> Path | None:
    name = "llama-server.exe" if os.name == "nt" else "llama-server"
    root = _root()
    if not root.is_dir():
        return None
    hits = sorted(root.rglob(name))
    return hits[0] if hits else None


def _model_path() -> Path:
    return _root() / "models" / MODEL_FILENAME


def status() -> dict[str, Any]:
    binary = _server_binary()
    model = _model_path()
    out: dict[str, Any] = {
        "supported": runtime_asset_name() is not None,
        "runtime_installed": binary is not None,
        "model_installed": model.is_file(),
        "ready": binary is not None and model.is_file(),
        "model_id": MODEL_ID,
        "model_label": MODEL_LABEL,
    }
    progress = _DOWNLOADS.get("install")
    if progress:
        out["download"] = {k: progress.get(k) for k in ("status", "stage", "downloaded", "total", "error")}
    return out


def start_install() -> dict[str, Any]:
    """背景下載 runtime（缺才抓）→ 模型（缺才抓）；UI 輪詢 status().download。"""
    if runtime_asset_name() is None:
        raise ValueError(f"不支援的平台：{platform.system()} {platform.machine()}")
    if status()["ready"]:
        return {"ok": True, "status": "done", "already_installed": True}
    with _DOWNLOAD_LOCK:
        current = _DOWNLOADS.get("install")
        if current and current.get("status") == "downloading":
            return {"ok": True, "status": "downloading",
                    **{k: current.get(k) for k in ("stage", "downloaded", "total")}}
        _DOWNLOADS["install"] = {"status": "downloading", "stage": "runtime",
                                 "downloaded": 0, "total": 0, "error": ""}
    threading.Thread(target=_install_worker, daemon=True).start()
    return {"ok": True, "status": "downloading"}


def _download_to(url: str, dest: Path, state: dict[str, Any]) -> None:
    """.part 串流＋原子搬移（半包永遠不會看起來像裝好了）；進度寫進 state。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "yt-note-app"})
    with urllib.request.urlopen(request, timeout=120) as resp:
        state["total"] = int(resp.headers.get("Content-Length") or 0)
        state["downloaded"] = 0
        with open(tmp, "wb") as handle:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                state["downloaded"] += len(chunk)
    tmp.replace(dest)


def _extract_runtime(archive: Path) -> None:
    target = _root() / "runtime"
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(target, filter="data")
    archive.unlink(missing_ok=True)
    binary = _server_binary()
    if binary is None:
        raise ValueError("runtime 解壓完成但找不到 llama-server 執行檔")
    if os.name != "nt":
        binary.chmod(binary.stat().st_mode | 0o755)


def _install_worker() -> None:
    state = _DOWNLOADS["install"]
    try:
        if _server_binary() is None:
            state["stage"] = "runtime"
            asset = runtime_asset_name()
            archive = _root() / asset
            _download_to(f"{_RUNTIME_URL_BASE}/{asset}", archive, state)
            _extract_runtime(archive)
        if not _model_path().is_file():
            state["stage"] = "model"
            _download_to(MODEL_URL, _model_path(), state)
        state["status"] = "done"
    except Exception as exc:  # noqa: BLE001 — any failure must surface to the UI, not crash the thread
        state["status"] = "error"
        state["error"] = str(exc)


def _health_ok(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{_PORT}/health", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def ensure_server() -> None:
    """需要時才起 llama-server（lazy）；已有健康的就沿用。"""
    global _SERVER_PROC
    if _health_ok():
        return
    binary = _server_binary()
    if binary is None or not _model_path().is_file():
        raise ValueError("內建本機 AI 尚未安裝——請先在精靈或設定完成下載")
    with _SERVER_LOCK:
        if _health_ok():
            return
        argv = [str(binary), "-m", str(_model_path()), "--host", "127.0.0.1",
                "--port", str(_PORT), "-c", "8192", "--jinja", "--no-webui"]
        _SERVER_PROC = subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(binary.parent))
        import time
        for _ in range(_SPAWN_WAIT_SECONDS * 2):
            if _health_ok(0.5):
                return
            if _SERVER_PROC.poll() is not None:
                raise ValueError(f"llama-server 啟動失敗（exit {_SERVER_PROC.returncode}）")
            time.sleep(0.5)
        raise ValueError(f"llama-server {_SPAWN_WAIT_SECONDS}s 內未就緒（模型載入過慢或記憶體不足）")


def stop_server() -> None:
    global _SERVER_PROC
    with _SERVER_LOCK:
        if _SERVER_PROC and _SERVER_PROC.poll() is None:
            _SERVER_PROC.terminate()
            try:
                _SERVER_PROC.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _SERVER_PROC.kill()
        _SERVER_PROC = None


def chat(prompt: str, system: str | None, json_mode: bool, json_schema: dict[str, Any] | None,
         max_tokens: int) -> tuple[str, dict[str, Any]]:
    ensure_server()
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}]
    body: dict[str, Any] = {"messages": messages, "max_tokens": max_tokens}
    if json_schema:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "out", "schema": json_schema}}
    elif json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        f"http://127.0.0.1:{_PORT}/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as exc:
        raise ValueError(f"內建本機 AI 呼叫失敗：{exc}") from exc
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    return text, {"input": usage.get("prompt_tokens"), "output": usage.get("completion_tokens")}
