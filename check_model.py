"""真实调用一次：开放题打分 + 写报告。用来验证 key 和模型链路。

    python check_model.py
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SECRETS = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"


def main() -> None:
    key = tomllib.load(open(SECRETS, "rb")).get("deepseek_api_key", "")
    if not key:
        print("secrets.toml 里没有 deepseek_api_key")
        return
    os.environ["DEEPSEEK_API_KEY"] = key

    import llm
    from report import render_report
    from scoring import decide
    from test_flow import CHOICES, OPEN_ANSWERS
    from test_scoring import build

    answers = build(CHOICES, {})
    for qid, text in OPEN_ANSWERS.items():
        answers[qid]["text"] = text
        answers[qid].pop("score", None)

    scores = llm.rate_open_answers(answers)
    if not scores:
        print("打分失败：模型没返回可解析的 JSON")
        return
    print(f"打分成功，{len(scores)} 题：{dict(sorted(scores.items()))}\n")

    for qid, score in scores.items():
        answers[qid]["score"] = score

    decision = decide(answers)
    print(f"总分 {decision['score100']}　路径 {decision['path']}　分层 {decision['layers']}\n")

    report = llm.write_report(answers, decision)
    if report:
        print("=" * 30, "模型版报告", "=" * 30)
        print(report)
    else:
        print("报告生成失败，退回模板：\n")
        print(render_report(answers, decision, model_scores=True))


if __name__ == "__main__":
    main()
