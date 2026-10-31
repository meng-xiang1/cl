"""无头测试：走完整个流程，确认 48 题能答完、能出报告、分数在合理区间。

不依赖模型（没有 key 时走规则兜底）。
    python test_flow.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from streamlit.testing.v1 import AppTest  # noqa: E402

from questions import FLOW  # noqa: E402

# 一套「典型上班族想创业」的答案：意图强，证据弱
OPEN_ANSWERS = {
    11: "我希望五年后九点起床，在自己开的店里，跟两个员工一起理货，下午见供应商。",
    12: "羡慕他们自由、赚钱多。怕的是没收入，还有求人。",
    14: "靠谱、想得多、不太会来事。最不准的是不太会来事。",
    15: "大概第三个月开始紧张，第六个月要动存款，第九个月得找兼职。",
    16: "8 万",
    18: "失败就是钱没了。我会跟家里说我想清楚了，不后悔。",
    19: "没有，最多基金亏过一点。",
    22: "没有，都是拿工资。大学时帮人代过课，一次五十块。",
    23: "没有正经卖过东西。",
    25: "组织过一次同学聚会，二十多个人，订场地收钱都是我。",
    27: "PPT 做得还行，但没人单独给过钱。",
    28: "公司让我做新业务，没人带，我自己摸出来的。",
    29: "提的方案被领导否了。后来我按他的意思改了一版，过了。",
    30: "写方案吧。验证就是领导一直用我写的。",
    32: "打算拿 15 万，自己存款，已经在了。",
    33: "认识三个供应商，一个是我表哥的朋友。",
    37: "一年",
    45: "家里其实有积蓄，我爸妈能撑我一段时间。",
    46: "7 分。因为我经常拖到最后一刻才动手。",
    47: "会有点不服气，但我更怕亏钱。",
    48: "有一点，我把存款说多了。",
}

CHOICES = {
    # 题号: 选项下标
    1: 3,
    2: 2,
    3: 1,
    4: 3,
    5: 2,
    6: 1,
    7: 2,
    8: 3,
    9: 1,
    10: 0,
    13: 1,
    17: 0,
    20: 1,
    21: 1,
    24: 2,
    26: 2,
    31: 1,
    34: 1,
    35: 0,
    36: 1,
    38: 1,
    39: 0,
    40: 1,
    41: 0,
    42: 0,
    43: 0,
    44: 0,
}


def run() -> None:
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception, at.exception

    at.button(key="start").click().run()
    assert not at.exception, at.exception

    for step in range(80):
        idx = at.session_state["idx"]
        if at.session_state["report"]:
            print(f"完成，用了 {step} 步")
            break
        q = FLOW[idx]
        if q.kind == "choice":
            at.button(key=f"opt_{q.id}_{CHOICES.get(q.id, 0)}").click().run()
        else:
            at.chat_input[0].set_value(OPEN_ANSWERS.get(q.id, "")).run()
        assert not at.exception, f"第 {q.id} 题出错：{at.exception}"
    else:
        raise AssertionError("80 步还没走完，流程卡住了")

    decision = at.session_state["decision"]
    print("总分", decision["score100"])
    print("路径", decision["path"], "备选", decision["backup"])
    print("分层", decision["layers"])
    print("窗口", decision["window"], "红旗", [f["code"] for f in decision["flags"]])
    report = at.session_state["report"]
    print("报告字数", len(report))
    print("---- 报告开头 ----")
    print("\n".join(report.splitlines()[:12]))

    assert 0 <= decision["score100"] <= 100
    assert "一句话结论" in report


if __name__ == "__main__":
    import os
    import traceback

    ok = True
    try:
        run()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        ok = False
    sys.stdout.flush()
    # 沙箱里 Streamlit 的临时目录删不掉，退出时会刷一屏 PermissionError，这里直接走。
    os._exit(0 if ok else 1)
