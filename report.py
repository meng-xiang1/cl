"""报告渲染：把答案和评分拼成 Markdown。不调用模型，任何时候都能出结果。

模型版报告更自然（见 llm.write_report）。这里是兜底，原则是只说有证据的话：
- 只有被模型按锚点评过分的开放题，才允许出现在「支撑」和「拖死」里；
- 没有模型评分时，干脆不写这两段，改列硬事实，而不是拿长度启发式冒充分析。
"""

from __future__ import annotations

from typing import Any

from questions import BY_ID, FLOW
from scoring import PATHS, answer_score

LAYER_NAMES = {
    "L1": "动机",
    "L2": "风险与钱",
    "L3": "你做过什么",
    "L4": "手里的牌",
    "L5": "情景判断",
}

WEAK_HINT = {
    "L1": "动机这一层偏弱：要么还没想清楚为什么做，要么现在只是待得不舒服。这两件事撑不了两年。",
    "L2": "风险这一层偏弱：手上的现金和亏损承受力，撑不到验证周期结束。",
    "L3": "证据这一层偏弱：你还拿不出「靠自己赚到钱」的记录。这是整套里最硬的一条。",
    "L4": "牌面这一层偏弱：钱、人、客户都还没着落，现在开张等于从零起步。",
    "L5": "判断这一层偏弱：遇到现金流、合伙这类关键节点，你的默认选择风险偏高。",
}

NEGATIVE = ("没人", "没有", "没给过", "不太会", "不行", "一般")


def _clip(text: str, n: int = 70) -> str:
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[:n] + "…"


def answer_display(qid: int, answers: dict[int, dict[str, Any]]) -> str:
    q = BY_ID[qid]
    a = answers.get(qid)
    if not a:
        return "（跳过）"
    if q.kind == "choice":
        idx = a.get("value")
        if isinstance(idx, int) and 0 <= idx < len(q.options):
            return q.options[idx]
        return "（跳过）"
    return str(a.get("text", "")).strip() or "（跳过）"


def _model_scored(qid: int, answers: dict[int, dict[str, Any]]) -> bool:
    """这一题的分是不是模型按锚点给的（选择题的分天然可信）。"""
    q = BY_ID[qid]
    if q.kind == "choice":
        return True
    a = answers.get(qid) or {}
    return isinstance(a.get("score"), (int, float))


def evidence(answers: dict[int, dict[str, Any]], limit: int = 3) -> list[tuple[str, str]]:
    rows: list[tuple[int, float, int, str]] = []
    for q in FLOW:
        if not q.label or not _model_scored(q.id, answers):
            continue
        score = answer_score(q.id, answers.get(q.id))
        if score is None or score < 4:
            continue
        text = answer_display(q.id, answers)
        if len(text) < 2 or text == "（跳过）":
            continue
        # 开放题优先：同样是 5 分，他自己讲的事比一个选项标签更有说服力
        rows.append((0 if q.kind == "open" else 1, -score, q.id, text))
    rows.sort()
    return [(BY_ID[qid].label, _clip(text)) for _, _, qid, text in rows[:limit]]


def risks(answers: dict[int, dict[str, Any]], decision: dict[str, Any], limit: int = 2) -> list[str]:
    out: list[str] = [f["text"] for f in decision["flags"]]
    out.extend(decision["vetoes"])

    scored: list[tuple[float, int]] = []
    for q in FLOW:
        if not q.label or q.layer in {"L0", "L6"} or not _model_scored(q.id, answers):
            continue
        score = answer_score(q.id, answers.get(q.id))
        if score is None:
            continue
        scored.append((score, q.id))
    scored.sort()
    for score, qid in scored:
        if len(out) >= limit:
            break
        item = f"「{BY_ID[qid].label}」偏弱：{_clip(answer_display(qid, answers), 40)}"
        if item not in out:
            out.append(item)
    return out[:limit]


def hard_numbers(answers: dict[int, dict[str, Any]], decision: dict[str, Any]) -> dict[str, str]:
    return {
        "全职窗口期": f"约 {decision['window']} 个月",
        "最大可亏": answer_display(16, answers),
        "时间投入": answer_display(36, answers),
    }


def experiments(answers: dict[int, dict[str, Any]]) -> list[str]:
    """30 天最小验证：能用的技能就用自己的，用不了就退回通用版。"""
    ideas: list[str] = []
    skill = answer_display(27, answers)
    if len(skill) > 4 and skill != "（跳过）" and not any(w in skill for w in NEGATIVE):
        ideas.append(f"把你说的那件事（{_clip(skill, 26)}）卖 3 次，单价不低于 300 元。")
    if not ideas:
        ideas.append("挑一件你已经会的事，在 30 天内卖给 3 个陌生人，单价不低于 300 元。")
    ideas.append("判定标准：30 天内收到 900 元以上真实付款，且至少 1 个客户是陌生人。")
    ideas.append("一个客户都没有，别改方案，先换一个卖法再试 30 天。")
    return ideas


def score_table(decision: dict[str, Any]) -> str:
    lines = ["| 维度 | 得分（0–5） | 权重 |", "| --- | --- | --- |"]
    weights = {"L1": "20%", "L2": "25%", "L3": "30%", "L4": "15%", "L5": "10%"}
    for layer, name in LAYER_NAMES.items():
        lines.append(f"| {name} | {decision['layers'][layer]} | {weights[layer]} |")
    return "\n".join(lines)


def render_report(
    answers: dict[int, dict[str, Any]],
    decision: dict[str, Any],
    *,
    model_scores: bool = False,
) -> str:
    path = PATHS[decision["path"]]
    backup = PATHS[decision["backup"]]
    parts: list[str] = []

    parts.append(f"## 一句话结论\n\n你现在的状态，更接近「{decision['path']}：{path['name']}」。\n")

    if decision["flags"]:
        parts.append(
            f"> 先说一句：你头上有 {len(decision['flags'])} 个硬约束，"
            "任何一条都足够让「裸辞创业」变成高风险动作。下面的建议都建立在「不裸辞」的前提下。\n"
        )

    parts.append(
        f"## 主路径 / 备路径\n\n"
        f"**主：{decision['path']} · {path['name']}** — {path['one_line']}\n\n"
        f"{path['why']}\n\n"
        f"**备：{decision['backup']} · {backup['name']}** — 主路径 12 个月没跑通，退到这里。\n\n"
        f"### 下一步\n\n{path['next']}\n"
    )

    if model_scores:
        ev = evidence(answers)
        if ev:
            parts.append("## 支撑你的几件事\n")
            parts.extend(f"- **{label}**：{text}" for label, text in ev)
            parts.append("")
        rk = risks(answers, decision)
        if rk:
            parts.append("## 会拖死你的点\n")
            parts.extend(f"- {item}" for item in rk)
            parts.append("")

    hn = hard_numbers(answers, decision)
    parts.append("## 你的硬数字\n")
    parts.append(" · ".join(f"{k}：{v}" for k, v in hn.items()) + "\n")

    if decision["flags"]:
        parts.append("## 硬约束清单\n")
        parts.extend(f"- {f['text']}" for f in decision["flags"])
        parts.append("")

    if decision["notes"]:
        parts.append("## 前后对不上的地方\n")
        parts.extend(f"- {n}" for n in decision["notes"])
        parts.append("")

    parts.append("## 30 天最小验证\n")
    for i, item in enumerate(experiments(answers), 1):
        parts.append(f"{i}. {item}")
    parts.append("")

    parts.append(
        "## 12 个月检查点\n\n"
        "连续 3 个月副业收入 ≥ 主业的 40%，再谈辞职。没到这个数，就继续用业余时间试。\n"
    )

    parts.append("## 分数明细\n")
    parts.append(score_table(decision))
    parts.append(f"\n总分 **{decision['score100']} / 100**（五层加权）。\n")

    weakest = decision["weakest"]
    parts.append(f"**最弱的一层是「{LAYER_NAMES[weakest]}」（{decision['layers'][weakest]} / 5）。**")
    parts.append(WEAK_HINT[weakest] + "\n")

    if not model_scores:
        parts.append(
            "\n---\n\n> 这份报告由规则模板生成（没有配置模型，或模型调用失败）。"
            "结论和分数可以看；「支撑你的事」「拖死你的点」这两段需要模型读你的原话，这次跳过了。\n"
        )
    return "\n".join(parts)
