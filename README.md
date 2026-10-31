# 打工还是创业 · 测评 Agent

一个聊天式测评：48 道题，20–25 分钟，最后给一份「你现在该走哪条路」的报告。

不是「打工 or 创业」二选一，而是五档里的哪一档：

| 档 | 路径 | 一句话 |
|---|---|---|
| A | 融资型创业 | 高增长、要团队、要资本，能接受归零 |
| B | 小生意 / 个体经营 | 有雇工、有现金流、能复制，但不追求爆发 |
| C | 自由职业 / 技能变现 | 一个人 + 一门手艺，低杠杆、低风险 |
| D | 组织内发展 | 在别人的平台上放大自己 |
| E | 先副业验证 | 不裸辞，先跑出第一笔非工资收入 |

---

## 本地跑

```powershell
cd D:\程子龙\Documents\deepseek\career-fit
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

打开 `http://localhost:8501`。

**不配模型也能用**：这时报告由规则模板生成（照样有分数、路径、硬数字、30 天验证），
只是少了「支撑你的事 / 拖死你的点」这两段基于原话的分析。

---

## 配模型（强烈建议）

DeepSeek 的 key 放在下面任意一处，优先级从上到下：

1. 环境变量 `DEEPSEEK_API_KEY`
2. `.streamlit/secrets.toml` 里的 `deepseek_api_key`
3. 本目录下的 `.deepseek_key` 文件（放一行 key）

```powershell
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
notepad .streamlit\secrets.toml     # 把 sk-你的key 换成真的
```

`secrets.toml` 已经在 `.gitignore` 里，不会被提交。

模型只干两件事：给开放题按锚点打 0–5 分，以及把结构化结果写成人话。
**分数和路径是规则算的，模型改不了。**

---

## 变成公网链接（给别人测）

### 方案一：Streamlit Community Cloud（永久链接，推荐）

1. 在 GitHub 新建一个仓库，把 **career-fit 目录里的内容**作为仓库根目录推上去。
2. 打开 <https://share.streamlit.io>，用 GitHub 登录 → New app → 选仓库 → Main file path 填 `app.py`。
3. 在 Advanced settings → Secrets 里粘：

```toml
deepseek_api_key = "sk-真实的key"
deepseek_model = "deepseek-chat"
access_code = "cf-2026"      # 选填，填了就变内测
```

4. Deploy。拿到 `https://xxx.streamlit.app` 就能直接发给人。

> 注意：Streamlit Cloud 的文件系统是临时的，`results/` 里的结果会在重启后丢失。
> 想长期留存，看下面的「结果落地」。

### 方案二：cloudflared 临时隧道（5 分钟，链接会变）

本机跑着 `streamlit run app.py`，另开一个窗口：

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:8501
```

它会打印一个 `https://xxx.trycloudflare.com`，发给谁都能打开。
代价是电脑要开着、关了就断、每次重启换链接。

### 方案三：自己的服务器

```bash
pip install -r requirements.txt
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

前面挂 Nginx + 证书即可。这种模式下 `results/` 会真的落到磁盘上。

---

## 访问码与费用

公网地址 + 你的 API key = 陌生人可以烧你的 token。

在 secrets 里加 `access_code = "..."`，所有人进门要先输码。
另外每份测评大约消耗 2–4 次模型调用（一次批量打分 + 一次写报告），
按 DeepSeek 的价格，一个人测一次是厘级成本，不心疼。但被刷就不一样了，所以访问码别省。

---

## 结果落地

每份完成的测评会写一个 JSON 到 `results/`，包含分层得分、路径、全部答案和报告。
自己看汇总：

```powershell
python -c "import json,glob;[print(json.load(open(f,encoding='utf-8'))['at'], json.load(open(f,encoding='utf-8'))['score100'], json.load(open(f,encoding='utf-8'))['path']) for f in sorted(glob.glob('results/*.json'))]"
```

Streamlit Cloud 上这个目录是临时的。要长期存，把 `save_result()` 改成写数据库或 S3。

---

## 改题

题库全在 `questions.py`，是纯数据。改文字、改选项、改分值只动这一个文件，
评分引擎和界面都不用碰。

- `kind="choice"`：选项和分值一一对应，分值 0–5。
- `kind="open"`：由模型按 `rubric` 打分，`rubric` 写清 0/2/4/5 各是什么样。
- `follow=True`：答案不到 20 字时，模型会追问一句。

改完分层权重去 `LAYER_WEIGHTS`，改路径判定去 `scoring.decide()`。

---

## 目录结构

```
app.py              界面与流程（三个屏：介绍 / 答题 / 报告）
questions.py        48 道题，纯数据
scoring.py          评分、硬约束、短板否决、路径判定
llm.py              DeepSeek：打分 / 追问 / 写报告
report.py           规则版报告（没模型时兜底）
test_flow.py        无头走完 48 题，验证流程
test_scoring.py     三个人设，验证路径能拉开
```

跑测试：

```powershell
python test_scoring.py
python test_flow.py
```

---

## 设计上的几个选择

- **分数由规则算，不由模型算。** 模型只给开放题打 0–5 的分（按写死的锚点），
  合成总分、路径、否决规则全是确定性代码。这样同一个人的答案，结论永远一样。
- **硬约束不评分，只算窗口。** 「现金能撑几个月」不该换算成分数，
  它直接决定你只有几个月的试错时间。
- **短板一票否决。** 售卖能力 ≤ 2 分，总分再高也不给 A/B——创业是木桶。
- **跳过等于 0 分。** 否则跳过就成了免费选项。
- **不预测收入、不推荐项目。** 报告只谈「你现在这套条件适合走哪条路」和「下一步做什么」。

---

## 已知限制

- 没有身份校验，访问码是唯一门槛。
- Streamlit Cloud 上结果不持久。
- 开放题打分依赖模型，同一段落可能在不同模型版本下有 1 分的浮动。
- 报告里不包含任何心理诊断，也不该被当成职业咨询。
