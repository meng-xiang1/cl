"""DeepSeek 调用层：开放题评分、追问、写报告。

三个函数都遵守同一个约定：失败返回 None，绝不抛异常给界面。
没有 API key 时整个应用仍然可用（走规则兜底）。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from questions import BY_ID, FLOW

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE = "https://api.deepseek.com"

SCORE_SYSTEM = """你是「打工还是创业」测评的评分员。你只做一件事：按给定的评分锚点，给每道开放题打 0–5 分。

规则：
1. 只根据用户写的内容打分，不脑补。答得太短、答非所问，按低分。
2. 用户说「没有」「没做过」不算态度问题，但这一题就只能拿锚点里对应的低分。
3. 分数只能是 0、1、2、3、4、5 里的整数。
4. 不评价用户这个人，只评价这个答案落在锚点的哪一档。
5. 只输出 json，格式：{"scores": {"题号": 分数}}，不要任何解释。"""

REPORT_SYSTEM = """你是一个给成年人做职业路径评估的顾问。你要把结构化结果写成一份他自己愿意读完的报告。

必须遵守：
1. 只使用我给的事实和数字，不要编造经历、收入、行业。
2. 引用他自己说过的话（我给的原话），用「」括起来。
3. 不承诺成功，不预测收入，不说「你一定能成」「你很有天赋」这类空话。
4. 不说「你应该更自信」这种正确的废话。每一条建议都要能落到具体动作和数字。
5. 结论是适配度，不是判决。用「现阶段」「按你现在的条件」限定，不要下定论。
6. 语气平实，像朋友里那个说话最直的人。不用感叹号，不用 emoji。
7. 不要提题号（不要说「第 39 题」），直接说他说了什么、选了什么。
8. 「12 个月检查点」里的周期要和「12 个月」对得上，不要自己改成 6 个月。
9. 中文，总长度 700–1000 字。"""


def get_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    try:
        import streamlit as st

        key = str(st.secrets.get("deepseek_api_key", "")).strip()
        if key:
            return key
    except Exception:  # noqa: BLE001 - 没有 streamlit 环境时静默跳过
        pass
    key_file = os.path.join(os.path.dirname(__file__), ".deepseek_key")
    if os.path.exists(key_file):
        with open(key_file, encoding="utf-8") as fh:
            return fh.read().strip()
    return ""


def get_model() -> str:
    model = os.environ.get("DEEPSEEK_MODEL", "").strip()
    if model:
        return model
    try:
        import streamlit as st

        model = str(st.secrets.get("deepseek_model", "")).strip()
        if model:
            return model
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_MODEL


def _client():
    key = get_api_key()
    if not key:
        return None
    from openai import OpenAI

    base = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE)
    return OpenAI(api_key=key, base_url=base, timeout=90, max_retries=1)


def _chat(system: str, user: str, *, temperature: float, json_mode: bool = False) -> str | None:
    client = _client()
    if client is None:
        return None
    kwargs: dict[str, Any] = {
        "model": get_model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": 2000,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()
    except Exception:  # noqa: BLE001 - 网络/额度/模型问题一律降级
        return None


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def rate_open_answers(answers: dict[int, dict[str, Any]]) -> dict[int, float] | None:
    """一次性给所有还没打分的开放题打分。返回 {题号: 0–5}。"""
    items = []
    for q in FLOW:
        if q.kind != "open" or not q.rubric:
            continue
        a = answers.get(q.id)
        if not a or not str(a.get("text", "")).strip():
            continue
        items.append(
            {
                "题号": q.id,
                "题目": q.text.replace("**", ""),
                "评分锚点": q.rubric,
                "回答": str(a["text"]).strip()[:600],
            }
        )
    if not items:
        return {}

    user = (
        "下面是待评分的开放题，请按每题给出的锚点打分。只输出 json。\n\n"
        + json.dumps(items, ensure_ascii=False, indent=1)
        + '\n\n输出格式：{"scores": {"题号": 分数}}'
    )
    raw = _chat(SCORE_SYSTEM, user, temperature=0.1, json_mode=True)
    data = _extract_json(raw or "")
    if not data:
        return None
    scores_raw = data.get("scores") or data
    out: dict[int, float] = {}
    for k, v in scores_raw.items():
        try:
            qid = int(str(k).strip())
            if qid not in BY_ID:
                continue
            out[qid] = max(0.0, min(5.0, float(v)))
        except (TypeError, ValueError):
            continue
    return out or None


def followup_text(qid: int, answer: str) -> str | None:
    """答案太短时，生成一句追问。只问一层。"""
    q = BY_ID.get(qid)
    if not q:
        return None
    prompt = (
        f"用户回答了这道题：{q.text.replace('**', '')}\n"
        f"他的回答是：「{answer[:300]}」\n\n"
        "他的回答太空泛，缺少具体事实。请生成一句追问，逼出一个具体细节（时间、金额、人数、对象）。\n"
        "要求：一句话，不超过 30 字，口语，不要重复他的原话，不要评价，不要问两个问题。"
    )
    raw = _chat(
        "你是一个提问很准的访谈者。你只输出那一句追问本身，不加引号，不加解释。",
        prompt,
        temperature=0.7,
    )
    if not raw:
        return None
    line = raw.strip().splitlines()[0].strip().strip("「」\"'")
    return line[:60] or None


def write_report(
    answers: dict[int, dict[str, Any]],
    decision: dict[str, Any],
) -> str | None:
    """让模型按固定结构写报告。失败返回 None，由调用方走模板。"""
    from scoring import PATHS

    path = PATHS[decision["path"]]
    backup = PATHS[decision["backup"]]

    qa = []
    for q in FLOW:
        a = answers.get(q.id)
        if not a:
            continue
        if q.kind == "choice":
            idx = a.get("value")
            text = q.options[idx] if isinstance(idx, int) and 0 <= idx < len(q.options) else ""
        else:
            text = str(a.get("text", "")).strip()
        follow = a.get("follow")
        if follow:
            text = f"{text}（追问后补充：{follow}）"
        qa.append({"题号": q.id, "维度": q.layer, "题目": q.text.replace("**", ""), "回答": text[:500]})

    payload = {
        "结论": {
            "路径": f"{decision['path']} · {path['name']}",
            "路径含义": path["one_line"],
            "备选": f"{decision['backup']} · {backup['name']}",
            "总分": decision["score100"],
            "各维度得分": decision["layers"],
            "全职窗口期_月": decision["window"],
            "硬约束": [f["text"] for f in decision["flags"]],
            "短板否决": decision["vetoes"],
            "前后矛盾": decision["notes"],
        },
        "问答记录": qa,
    }

    structure = """按下面的结构写，用 Markdown，二级标题不要改：

## 一句话结论
一句话，直接说结论和路径，不要铺垫。

## 你为什么是这个路径
3 句话以内，用他自己的证据解释。必须引用他原话。

## 支撑你的三件事
三条，每条一句，引原话或数字。

## 会拖死你的两个点
两条，每条一句，说清楚会在什么时候要命。

## 你的硬数字
把全职窗口期、最大可亏金额、每周投入写出来。

## 30 天最小验证
3 条具体动作，要有金额、次数、判定标准。是他现在就能做的。

## 12 个月检查点
一条，说明达到什么条件再谈辞职。
"""
    raw = _chat(
        REPORT_SYSTEM,
        "这是结构化数据：\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
        + "\n\n"
        + structure,
        temperature=0.6,
    )
    if not raw or len(raw) < 200:
        return None
    return raw
