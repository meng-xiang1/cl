"""评分引擎：把 48 道题的答案，算成一个可解释的结论。

这里全部是确定性的规则，没有模型参与。模型只负责两件事：
1. 给开放题按 rubric 打 0–5 分（结果写进 answers 的 score 字段）
2. 把结构化结果写成一份人话报告

所有数字都能追溯回具体题目，报告里引用的每一句都来自用户自己说的话。
"""

from __future__ import annotations

import re
from typing import Any

from questions import (
    BY_ID,
    FLOW,
    LAYER_WEIGHTS,
    SCORED_LAYERS,
    WINDOW_MONTHS,
)

Answers = dict[int, dict[str, Any]]

PATHS: dict[str, dict[str, str]] = {
    "A": {
        "name": "融资型创业",
        "one_line": "高增长、要团队、要资本，能接受归零。",
        "why": "你的证据、资源和风险承受同时够线，可以直接按一家公司来做。",
        "next": "先找人补你最弱的那一半（技术或销售），再谈融资。",
    },
    "B": {
        "name": "小生意 / 个体经营",
        "one_line": "有雇工、有现金流、能复制，但不追求爆发。",
        "why": "你有做生意的底子，但资本和团队还不足以支撑高增长路线。",
        "next": "先跑通一个能稳定回本的单元，再复制第二个。",
    },
    "C": {
        "name": "自由职业 / 技能变现",
        "one_line": "一个人 + 一门手艺，低杠杆、低风险。",
        "why": "你的技能有人买，但组织能力和资源储量还没到能雇人的程度。",
        "next": "把接单做成产品化报价，先让收入可预测。",
    },
    "D": {
        "name": "组织内发展",
        "one_line": "在别人的平台上放大自己，选对赛道和岗位。",
        "why": "现阶段自己做的胜率低于在平台上做的胜率，这不是能力问题，是位置问题。",
        "next": "换到更靠近钱和客户的岗位，把「能卖东西」这件事先练出来。",
    },
    "E": {
        "name": "先副业验证",
        "one_line": "不裸辞，用 6–12 个月跑出第一笔非工资收入再定。",
        "why": "方向可能是对的，但现在的证据和跑道不足以支撑全职投入。",
        "next": "用最小成本把「有人愿意付钱」这件事验证一次。",
    },
}

BACKUP = {"A": "B", "B": "C", "C": "E", "E": "D", "D": "E"}

_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def parse_months(text: str) -> int | None:
    """从『9 个月』『一年半』『半年』这类文本里抠出月数。"""
    if not text:
        return None
    t = text.strip()
    if m := re.search(r"(\d+(?:\.\d+)?)\s*(?:个)?月", t):
        return int(float(m.group(1)))
    if m := re.search(r"(\d+(?:\.\d+)?)\s*年", t):
        return int(float(m.group(1)) * 12)
    if "半年" in t:
        return 6
    if m := re.search(r"([一两二三四五六七八九])年半", t):
        return _CN_NUM[m.group(1)] * 12 + 6
    for word, n in _CN_NUM.items():
        if f"{word}个月" in t:
            return n
    if m := re.search(r"([一两二三四五六七八九十])年", t):
        return _CN_NUM[m.group(1)] * 12
    return None


def answer_score(qid: int, ans: dict[str, Any] | None) -> float | None:
    """单题 0–5 分。选择题查表，开放题用 LLM 给的分，没给就用兜底启发式。"""
    if not ans:
        return None
    q = BY_ID[qid]
    if q.kind == "choice":
        idx = ans.get("value")
        if idx is None:
            return 0.0  # 主动跳过按 0 计，否则跳过就变成了免费选项
        if isinstance(idx, int) and 0 <= idx < len(q.points):
            return float(q.points[idx])
        return None
    score = ans.get("score")
    if isinstance(score, (int, float)):
        return max(0.0, min(5.0, float(score)))
    return heuristic_open_score(str(ans.get("text", "")))


def heuristic_open_score(text: str) -> float:
    """没有模型时的兜底：看长度、有没有数字、有没有具体名词。粗糙但不出错。"""
    t = (text or "").strip()
    if len(t) < 4:
        return 0.0
    if t in {"没有", "无", "没", "没有。", "不清楚", "不知道"}:
        return 1.0
    score = 1.0
    if len(t) >= 20:
        score += 1.0
    if len(t) >= 60:
        score += 1.0
    if re.search(r"\d", t):
        score += 1.0
    if re.search(r"(第.个月|因为|所以|后来|当时|结果)", t):
        score += 0.5
    return min(5.0, round(score, 1))


def layer_scores(answers: Answers) -> dict[str, float]:
    """每层的 0–5 分 = 该层已作答题目的均值。没答的题不计入，但缺太多会有提示。"""
    out: dict[str, float] = {}
    for layer in SCORED_LAYERS:
        qs = [q for q in FLOW if q.layer == layer]
        vals = [v for q in qs if (v := answer_score(q.id, answers.get(q.id))) is not None]
        out[layer] = round(sum(vals) / len(vals), 2) if vals else 0.0
    return out


def hard_constraints(answers: Answers) -> dict[str, Any]:
    """L0 不评分，只算出「全职窗口期（月）」和红旗。"""
    flags: list[dict[str, str]] = []

    def val(qid: int) -> int | None:
        a = answers.get(qid)
        return a.get("value") if a and isinstance(a.get("value"), int) else None

    window = WINDOW_MONTHS.get(val(1) if val(1) is not None else 0, 0)

    if val(2) == 0:
        flags.append({"code": "big_expense", "text": "未来 12 个月有一笔不能推迟的大额支出"})
        window = min(window, 6)
    elif val(2) == 1:
        window = min(window, 12)

    if val(3) == 0:
        flags.append({"code": "sole_earner", "text": "家里的收入完全靠你"})
        window = min(window, 6)

    if val(4) == 2:
        flags.append({"code": "family_against", "text": "家人明确反对，且还没谈拢"})
    if val(5) in (0, 1):
        flags.append({"code": "energy", "text": "身体或精力撑不住长期高强度"})
    if val(6) == 0:
        flags.append({"code": "legal", "text": "存在法律或债务上的硬约束"})

    return {"window": window, "flags": flags}


def _consistency_notes(answers: Answers, window: int) -> list[str]:
    notes: list[str] = []
    stated = parse_months(str((answers.get(37) or {}).get("text", "")))
    if stated and window and stated > window * 1.5:
        notes.append(
            f"你说能撑 {stated} 个月不领工资，但按现金和家庭负担算，实际跑道只有 {window} 个月左右。"
        )
    a15 = str((answers.get(15) or {}).get("text", ""))
    if "18 个月" in a15 and window and window < 12:
        notes.append("你按『18 个月没收入』推演，但你的现金跑道撑不到那个长度。")
    return notes


def decide(answers: Answers) -> dict[str, Any]:
    """完整结论：分数、短板、路径、否决理由。"""
    layers = layer_scores(answers)
    hc = hard_constraints(answers)
    notes = _consistency_notes(answers, hc["window"])

    total = sum(layers[l] * LAYER_WEIGHTS[l] for l in SCORED_LAYERS)
    score100 = int(round(total * 20))

    vetoes: list[str] = []
    if hc["window"] < 6:
        vetoes.append(f"全职窗口只有约 {hc['window']} 个月，撑不到验证周期")
    if layers["L3"] <= 2.0:
        vetoes.append("还没有任何「靠自己赚到钱」的硬证据")
    if layers["L2"] <= 2.0:
        vetoes.append("抗风险能力偏弱：亏损经历和现金弹性都不够")

    # 先按总分定，再用短板覆盖
    if score100 >= 80 and layers["L3"] >= 4.0 and not hc["flags"] and hc["window"] >= 12:
        path = "A"
    elif score100 >= 65 and layers["L3"] >= 2.5:
        path = "B"
    elif score100 >= 50:
        path = "C"
    elif score100 >= 35:
        path = "E"
    else:
        path = "D"

    if layers["L3"] <= 2.0 or hc["window"] < 6:
        path = "E" if layers["L1"] >= 3.0 else "D"
    elif layers["L2"] <= 2.0:
        path = "E"

    weakest = min(SCORED_LAYERS, key=lambda l: layers[l])
    strongest = max(SCORED_LAYERS, key=lambda l: layers[l])

    return {
        "layers": layers,
        "score100": score100,
        "window": hc["window"],
        "flags": hc["flags"],
        "notes": notes,
        "vetoes": vetoes,
        "path": path,
        "backup": BACKUP[path],
        "weakest": weakest,
        "strongest": strongest,
    }


def aggregate_stats(results: list[dict[str, Any]]) -> dict[str, Any]:
    """给站长看的汇总。"""
    if not results:
        return {"count": 0}
    scores = [r["score100"] for r in results]
    dist: dict[str, int] = {}
    for r in results:
        dist[r["path"]] = dist.get(r["path"], 0) + 1
    return {
        "count": len(results),
        "avg": round(sum(scores) / len(scores), 1),
        "median": sorted(scores)[len(scores) // 2],
        "dist": dist,
    }
