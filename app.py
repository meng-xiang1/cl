"""打工还是创业 · 测评 Agent

一个人一次对话，走完 48 道题，出一份「你现在更适合哪条路」的报告。

运行：
    cd career-fit
    streamlit run app.py
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st

import llm
from questions import BY_ID, FLOW, LAYERS
from report import answer_display, render_report
from scoring import answer_score, decide

RESULT_DIR = Path(__file__).resolve().parent / "results"

st.set_page_config(
    page_title="打工还是创业",
    page_icon=":material/explore:",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------- 基础设施
def secret(key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(key, default)).strip()
    except Exception:  # noqa: BLE001 - 没有 secrets 文件时照常运行
        return default


def init_state() -> None:
    st.session_state.setdefault("answers", {})
    st.session_state.setdefault("idx", 0)
    st.session_state.setdefault("started", False)
    st.session_state.setdefault("report", None)
    st.session_state.setdefault("model_used", False)
    st.session_state.setdefault("pending", None)
    st.session_state.setdefault("started_at", None)
    st.session_state.setdefault("authed", False)


def advance() -> None:
    st.session_state.idx += 1
    if st.session_state.idx >= len(FLOW):
        finish()


def record_choice(qid: int, index: int) -> None:
    st.session_state.answers[qid] = {"value": index, "text": BY_ID[qid].options[index]}
    advance()


def record_open(qid: int, text: str) -> None:
    st.session_state.answers[qid] = {"text": text.strip()}
    q = BY_ID[qid]
    if q.follow and len(text.strip()) < 20 and llm.get_api_key():
        with st.spinner("想追问一句…"):
            probe = llm.followup_text(qid, text)
        if probe:
            st.session_state.pending = {"qid": qid, "text": probe}
            st.rerun()
    advance()


def finish() -> None:
    answers = st.session_state.answers

    model_scores = False
    with st.spinner("正在给开放题打分…"):
        scores = llm.rate_open_answers(answers)
    if scores:
        for qid, score in scores.items():
            if qid in answers:
                answers[qid]["score"] = score
        model_scores = True

    decision = decide(answers)

    with st.spinner("正在写报告…"):
        report = llm.write_report(answers, decision)
    if report:
        st.session_state.model_used = True
    else:
        report = render_report(answers, decision, model_scores=model_scores)
        st.session_state.model_used = model_scores

    decision["model_used"] = st.session_state.model_used
    st.session_state.report = report
    st.session_state.decision = decision
    save_result(answers, decision, report)


def save_result(answers: dict, decision: dict, report: str) -> None:
    try:
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        started = st.session_state.started_at or time.time()
        record = {
            "id": uuid.uuid4().hex[:10],
            "at": datetime.now().isoformat(timespec="seconds"),
            "minutes": round((time.time() - started) / 60, 1),
            "score100": decision["score100"],
            "path": decision["path"],
            "layers": decision["layers"],
            "window": decision["window"],
            "flags": [f["code"] for f in decision["flags"]],
            "model_used": decision.get("model_used", st.session_state.model_used),
            "answers": {str(k): v for k, v in answers.items()},
            "report": report,
        }
        (RESULT_DIR / f"{record['at'].replace(':', '')}-{record['id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001 - 存不下也不能挡住用户看报告
        import sys

        print(f"[save_result] 结果没有存下来：{type(exc).__name__}: {exc}", file=sys.stderr)


def restart() -> None:
    for key in ("answers", "idx", "report", "pending", "started_at", "model_used"):
        st.session_state.pop(key, None)
    st.session_state.decision = None
    st.session_state.started = False
    st.rerun()


# ---------------------------------------------------------------- 三个界面
def screen_gate() -> None:
    code = secret("access_code")
    if not code or st.session_state.authed:
        return
    st.title("打工还是创业")
    st.caption("这是一个内测地址，需要访问码。")
    entered = st.text_input("访问码", type="password", label_visibility="collapsed", placeholder="输入访问码")
    if st.button("进入", width="stretch"):
        if entered.strip() == code:
            st.session_state.authed = True
            st.rerun()
        st.error("访问码不对。")
    st.stop()


def screen_intro() -> None:
    st.title("打工还是创业")
    st.markdown("##### 48 道题，帮你判断现在该走哪条路")

    st.markdown(
        "这不是心理测试。它只问两件事：**你手里已经有什么**，以及**你现在扛得住什么**。"
        "\n\n"
        "- 大约 20–25 分钟，中途可以点「上一步」改答案\n"
        "- 会问金额、月数、人数这类具体数字，答得越具体越准\n"
        "- 没做过的事直接说没做过，这不会让你显得差，只会让结论更准\n"
        "- 结果是一份报告，不存你的姓名和联系方式"
    )

    st.divider()
    c1, c2 = st.columns([2, 1])
    with c1:
        if st.button("开始测评", type="primary", width="stretch", key="start"):
            st.session_state.started = True
            st.session_state.started_at = time.time()
            st.rerun()
    with c2:
        st.caption(f"共 {len(FLOW)} 题")

    st.caption(
        "结论是「适配度」，不是判决。它告诉你现在这条路顺不顺，"
        "不告诉你你行不行。人的条件会变，六个月后可以重测。"
    )


def render_history(upto: int) -> None:
    for q in FLOW[max(0, upto - 3) : upto]:
        with st.chat_message("assistant", avatar=":material/quiz:"):
            st.markdown(q.text)
        with st.chat_message("user"):
            st.markdown(answer_display(q.id, st.session_state.answers))
            follow = st.session_state.answers.get(q.id, {}).get("follow")
            if follow:
                st.caption(f"补充：{follow}")


def screen_chat() -> None:
    answers = st.session_state.answers
    idx = st.session_state.idx
    q = FLOW[idx]

    done = sum(1 for x in FLOW if answers.get(x.id))
    st.progress(done / len(FLOW), text=f"已答 {done} / {len(FLOW)}　·　当前：{LAYERS[q.layer]['title']}")

    render_history(idx)

    if idx == 0 or FLOW[idx - 1].layer != q.layer:
        st.divider()
        st.caption(LAYERS[q.layer]["title"])
        st.markdown(f"**{LAYERS[q.layer]['intro']}**")

    with st.chat_message("assistant", avatar=":material/quiz:"):
        st.markdown(q.text)
        if q.hint:
            st.caption(q.hint)

    if st.session_state.pending:
        with st.chat_message("assistant", avatar=":material/quiz:"):
            st.markdown(st.session_state.pending["text"])

    if q.kind == "choice":
        for i, option in enumerate(q.options):
            if st.button(option, key=f"opt_{q.id}_{i}", width="stretch"):
                record_choice(q.id, i)
                st.rerun()
        st.caption("选一个。都不合适就点跳题。")
    else:
        pending = st.session_state.pending
        placeholder = "补充一句就行" if pending else "尽量带上数字和细节…"
        if text := st.chat_input(placeholder):
            if len(text.strip()) < 2:
                st.toast("多写两个字，或者点跳过")
            elif pending:
                answers[pending["qid"]]["follow"] = text.strip()
                st.session_state.pending = None
                advance()
                st.rerun()
            else:
                record_open(q.id, text)
                st.rerun()

    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        if st.button("上一步", key=f"back_{q.id}", disabled=idx == 0, width="stretch"):
            prev = FLOW[idx - 1]
            answers.pop(prev.id, None)
            st.session_state.pending = None
            st.session_state.idx -= 1
            st.rerun()
    with c2:
        if st.button("跳过", key=f"skip_{q.id}", width="stretch"):
            if q.kind == "choice":
                answers[q.id] = {"value": None, "text": ""}
            else:
                answers[q.id] = {"text": ""}
            st.session_state.pending = None
            advance()
            st.rerun()
    with c3:
        st.caption("")


def screen_report() -> None:
    decision = st.session_state.get("decision") or {}
    st.title("你的报告")
    st.caption(
        f"总分 {decision.get('score100', '—')} / 100　·　路径 {decision.get('path', '—')}"
        f"　·　{'模型撰写' if st.session_state.model_used else '规则生成'}"
    )
    st.markdown(st.session_state.report)
    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "下载报告（Markdown）",
            data=st.session_state.report,
            file_name="打工还是创业-测评报告.md",
            mime="text/markdown",
            width="stretch",
        )
    with c2:
        if st.button("重新测一次", width="stretch", key="restart"):
            restart()

    st.caption(
        "这份报告只根据你刚才的回答生成，没有核实任何信息。"
        "它不是对你的判断，是对你现在这套条件的判断。"
    )


# ---------------------------------------------------------------- 路由
def main() -> None:
    init_state()
    screen_gate()

    if st.session_state.report:
        screen_report()
    elif not st.session_state.started:
        screen_intro()
    else:
        screen_chat()


main()
