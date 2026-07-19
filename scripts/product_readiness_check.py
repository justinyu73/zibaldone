#!/usr/bin/env python3
"""Deterministic source/release checks for the private product-ready baseline."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


# AGENTS.md（agent 操作協議）＝私有治理物，不列產品必要檔：公開樹刻意不含它。
REQUIRED_PATHS = (
    "README.md",
    "backend/requirements.txt",
    "frontend/package-lock.json",
    "frontend/src-tauri/Cargo.lock",
    "frontend/src-tauri/tauri.conf.json",
    "docs/install/windows.md",
    "docs/install/macos.md",
    "docs/install/development.md",
    "docs/privacy-and-network.md",
    "docs/troubleshooting.md",
)
FORBIDDEN_TRACKED_PARTS = {
    ".venv",
    "node_modules",
    "target",
    "__pycache__",
    ".pytest_cache",
    "test-results",
    ".local-assets",
}
FORBIDDEN_TRACKED_NAMES = {
    ".env",
    ".source_data_root",
    "config.json",
}
ARTIFACT_SUFFIXES = (".dmg", ".exe", ".app.tar.gz")
WARN_ARTIFACT_BYTES = 95_000_000
MAX_ARTIFACT_BYTES = 110_000_000
MAX_TRACKED_SOURCE_BYTES = 25_000_000


def git_files(root: Path) -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root
    ).decode("utf-8")
    return [item for item in output.split("\0") if item]


def source_checks(root: Path) -> tuple[list[str], list[str], dict[str, object]]:
    errors: list[str] = []
    warnings: list[str] = []
    tracked = git_files(root)
    existing_tracked = [relative for relative in tracked if (root / relative).is_file()]

    missing = [path for path in REQUIRED_PATHS if not (root / path).is_file()]
    if missing:
        errors.append("missing required files: " + ", ".join(missing))

    forbidden: list[str] = []
    for relative in existing_tracked:
        path = Path(relative)
        if FORBIDDEN_TRACKED_PARTS.intersection(path.parts):
            forbidden.append(relative)
        elif path.name in FORBIDDEN_TRACKED_NAMES:
            forbidden.append(relative)
        elif path.suffix.lower() in {".pem", ".p12", ".key"}:
            forbidden.append(relative)
    if forbidden:
        errors.append("forbidden tracked runtime/secret files: " + ", ".join(forbidden))

    source_bytes = sum((root / relative).stat().st_size for relative in existing_tracked)
    if source_bytes > MAX_TRACKED_SOURCE_BYTES:
        errors.append(
            f"tracked source is {source_bytes / 1_000_000:.1f} MB "
            f"(limit {MAX_TRACKED_SOURCE_BYTES / 1_000_000:.0f} MB)"
        )

    config_path = root / "frontend/src-tauri/tauri.conf.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        version = str(config.get("version") or "")
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            errors.append(f"invalid Tauri release version: {version!r}")
    else:
        version = ""

    return errors, warnings, {
        "tracked_files": len(existing_tracked),
        "tracked_source_bytes": source_bytes,
        "tauri_version": version,
    }


def artifact_checks(path: Path) -> tuple[list[str], list[str], dict[str, object]]:
    errors: list[str] = []
    warnings: list[str] = []
    artifacts = sorted(
        item for item in path.rglob("*")
        if item.is_file() and item.name.endswith(ARTIFACT_SUFFIXES)
    )
    if not artifacts:
        errors.append(f"no desktop installer/update artifact found under {path}")

    rows: list[dict[str, object]] = []
    for artifact in artifacts:
        size = artifact.stat().st_size
        rows.append({"name": artifact.name, "bytes": size})
        if size > MAX_ARTIFACT_BYTES:
            errors.append(
                f"{artifact.name} is {size / 1_000_000:.1f} MB "
                f"(hard limit {MAX_ARTIFACT_BYTES / 1_000_000:.0f} MB)"
            )
        elif size > WARN_ARTIFACT_BYTES:
            warnings.append(
                f"{artifact.name} is {size / 1_000_000:.1f} MB "
                f"(warning threshold {WARN_ARTIFACT_BYTES / 1_000_000:.0f} MB)"
            )
    return errors, warnings, {"artifacts": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--artifacts", default="")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    errors, warnings, details = source_checks(root)
    if args.artifacts:
        a_errors, a_warnings, a_details = artifact_checks(
            (root / args.artifacts).resolve()
        )
        errors.extend(a_errors)
        warnings.extend(a_warnings)
        details.update(a_details)

    report = {
        "schema": "yt-note-app-product-readiness/v1",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "details": details,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
