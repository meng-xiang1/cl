"""评分引擎的单元测试：三个人设，确认路径能拉开、分数单调。

    python test_scoring.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from questions import FLOW  # noqa: E402
from scoring import decide, parse_months  # noqa: E402


def build(choices: dict[int, int], opens: dict[int, float]) -> dict:
    answers: dict[int, dict] = {}
    for q in FLOW:
        if q.kind == "choice":
            answers[q.id] = {"value": choices.get(q.id, 0), "text": q.options[choices.get(q.id, 0)]}
        else:
            score = opens.get(q.id)
            answers[q.id] = {"text": "（测试用回答，长度足够触发启发式）", "score": score}
    return answers


# 1. 已经跑通过小生意的人
STRONG = build(
    {
        1: 4, 2: 2, 3: 2, 4: 0, 5: 3, 6: 1,
        7: 2, 8: 3, 9: 0, 10: 0, 13: 0,
        17: 0, 20: 0, 21: 1,
        24: 3, 26: 3, 31: 0,
        34: 2, 35: 1, 36: 0, 38: 0,
        39: 0, 40: 0, 41: 0, 42: 0, 43: 0, 44: 0,
    },
    {11: 5, 12: 5, 14: 4, 15: 5, 16: 5, 18: 5, 19: 5,
     22: 5, 23: 5, 25: 5, 27: 5, 28: 5, 29: 4, 30: 5,
     32: 5, 33: 5, 37: 5},
)

# 2. 想创业但只有工资记录的人
MID = build(
    {
        1: 3, 2: 2, 3: 1, 4: 3, 5: 2, 6: 1,
        7: 2, 8: 3, 9: 1, 10: 0, 13: 1,
        17: 0, 20: 1, 21: 1,
        24: 2, 26: 2, 31: 1,
        34: 1, 35: 0, 36: 1, 38: 1,
        39: 0, 40: 1, 41: 0, 42: 0, 43: 0, 44: 0,
    },
    {11: 3, 12: 3, 14: 3, 15: 3, 16: 3, 18: 3, 19: 2,
     22: 2, 23: 2, 25: 3, 27: 2, 28: 3, 29: 3, 30: 2,
     32: 3, 33: 2, 37: 3},
)

# 3. 家里全靠他、也没做过生意的人
WEAK = build(
    {
        1: 0, 2: 0, 3: 0, 4: 2, 5: 0, 6: 0,
        7: 3, 8: 0, 9: 2, 10: 1, 13: 2,
        17: 1, 20: 2, 21: 0,
        24: 0, 26: 0, 31: 2,
        34: 0, 35: 0, 36: 2, 38: 2,
        39: 3, 40: 2, 41: 1, 42: 1, 43: 1, 44: 2,
    },
    {11: 1, 12: 1, 14: 1, 15: 1, 16: 0, 18: 1, 19: 0,
     22: 0, 23: 0, 25: 0, 27: 0, 28: 0, 29: 1, 30: 0,
     32: 0, 33: 0, 37: 0},
)


def show(name: str, answers: dict) -> dict:
    d = decide(answers)
    print(
        f"{name:<8} 总分 {d['score100']:>3}  路径 {d['path']}（备 {d['backup']}）"
        f"  窗口 {d['window']:>2} 月  红旗 {len(d['flags'])}  分层 {d['layers']}"
    )
    return d


def main() -> None:
    s = show("强创业者", STRONG)
    m = show("典型上班", MID)
    w = show("纯打工型", WEAK)

    assert s["score100"] > m["score100"] > w["score100"], "分数没有拉开"
    assert s["path"] == "A", f"强人设应该到 A，实际 {s['path']}"
    assert m["path"] in {"B", "C", "E"}, f"中人设路径异常：{m['path']}"
    assert w["path"] == "D", f"弱人设应该到 D，实际 {w['path']}"

    # 硬约束：现金不到 3 个月 + 家里全靠他 → 窗口最多 6 个月
    assert w["window"] <= 6
    assert any(f["code"] == "sole_earner" for f in w["flags"])

    # 文本解析
    assert parse_months("9 个月") == 9
    assert parse_months("一年半") == 18
    assert parse_months("半年") == 6
    assert parse_months("两年") == 24
    assert parse_months("说不清") is None

    print("全部通过")


if __name__ == "__main__":
    main()
