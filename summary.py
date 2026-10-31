"""看一眼谁测过、结果落在哪。不依赖模型。

    python summary.py
"""

from __future__ import annotations

import json
from pathlib import Path

from scoring import PATHS

RESULTS = Path(__file__).resolve().parent / "results"


def main() -> None:
    files = sorted(RESULTS.glob("*.json"))
    if not files:
        print("还没有人测完。让他们打开页面走完 48 题，报告出来就会写到这里。")
        return

    rows = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rows.append(d)

    print(f"共 {len(rows)} 份\n")
    print(f"{'时间':<20}{'分钟':>5}  {'总分':>4}  {'路径':<26}窗口")
    print("-" * 72)
    for d in rows:
        path = f"{d['path']} · {PATHS.get(d['path'], {}).get('name', '')}"
        print(f"{d['at']:<20}{d.get('minutes', 0):>5}  {d['score100']:>4}  {path:<26}{d.get('window', '?')} 个月")

    if rows:
        scores = [d["score100"] for d in rows]
        print(f"\n平均 {sum(scores) / len(scores):.1f} 分，最高 {max(scores)}，最低 {min(scores)}")
        dist: dict[str, int] = {}
        for d in rows:
            dist[d["path"]] = dist.get(d["path"], 0) + 1
        print("分布：" + "　".join(f"{k} {v} 人" for k, v in sorted(dist.items())))
        print(f"\n完整报告在 {RESULTS}")


if __name__ == "__main__":
    main()
