#!/usr/bin/env python
"""大型 vault 效能 benchmark（JY commercial review P2）。

量「商業品質門檻」未驗的兩件：① index 刷新（refresh_index＝rglob+stat，cap 5000）
② 全文搜尋（search_notes，注意它每次都先 refresh_index＝重走磁碟）。
在 100/1k/5k 合成 vault 上跑，報 p50/p95，對照門檻 search p95 ≤500ms(1k)/1.5s(5k)。

跑法：backend/.venv/bin/python bench_vault.py [runs]
無 provider/network/credential；合成 vault 寫 temp、跑完刪。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import search_index as S  # noqa: E402

SIZES = [100, 1000, 5000]
QUERIES = ["會議", "決議", "transcript", "品質", "醫療筆記", "zzznomatch"]


def make_vault(root: Path, n: int) -> None:
    for i in range(n):
        sub = root / "02_Sources" / f"f{i % 20:02d}"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"note_{i:05d}.md").write_text(
            f"---\ntitle: 筆記 {i} 會議決議\ncreated: 2026-06-{(i % 28) + 1:02d}\n---\n\n"
            f"# 筆記 {i}\n\n這是第 {i} 篇會議筆記，討論轉錄品質與決議。transcript quality note {i}.\n"
            f"關鍵字：醫療筆記 決議 品質 行動項 {i}.\n" * 3,
            encoding="utf-8")


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def bench(n: int, runs: int) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix=f"bench-vault-{n}-"))
    try:
        make_vault(tmp, n)
        root = str(tmp)
        t0 = time.perf_counter()
        idx = S.refresh_index(root)  # cold：首次建索引
        cold_ms = (time.perf_counter() - t0) * 1000
        lat = []
        for k in range(runs):
            q = QUERIES[k % len(QUERIES)]
            t = time.perf_counter()
            S.search_notes(root, q, limit=50)  # 含每次的 refresh_index 重走
            lat.append((time.perf_counter() - t) * 1000)
        return {"n": n, "indexed": idx.get("indexed", idx.get("total", "?")),
                "cold_index_ms": cold_ms, "search_p50": pct(lat, 50), "search_p95": pct(lat, 95)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            S._db_path(Path(root)).unlink(missing_ok=True)  # 清掉這個 vault 的 index DB
        except Exception:
            pass


def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    print(f"vault perf benchmark（runs={runs}/size）\n")
    print(f"{'notes':>6} | {'cold index ms':>14} | {'search p50 ms':>14} | {'search p95 ms':>14} | budget p95")
    print("-" * 78)
    budgets = {100: "—", 1000: "≤500", 5000: "≤1500"}
    for n in SIZES:
        r = bench(n, runs)
        flag = ""
        if n in (1000, 5000):
            cap = 500 if n == 1000 else 1500
            flag = "  ✗ 超標" if r["search_p95"] > cap else "  ✓"
        print(f"{r['n']:>6} | {r['cold_index_ms']:>14.1f} | {r['search_p50']:>14.1f} | "
              f"{r['search_p95']:>14.1f} | {budgets[n]:>8}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
